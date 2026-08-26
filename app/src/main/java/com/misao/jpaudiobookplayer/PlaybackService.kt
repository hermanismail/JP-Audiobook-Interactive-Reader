package com.misao.jpaudiobookplayer

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.Bitmap
import android.os.Binder
import android.os.IBinder
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.media.app.NotificationCompat.MediaStyle

private const val CHANNEL_ID = "playback"
private const val NOTIFICATION_ID = 1

/**
 * Foreground service holding the app's `MediaSessionCompat` and the
 * lock-screen/notification media control. Deliberately thin: it owns no
 * playback state of its own beyond what it's told - actual audio lives in
 * the WebView's `<audio>` element inside MainActivity. This service just
 * mirrors that into a MediaSession (so it's the one thing the Android
 * system actually observes for lock-screen controls, Bluetooth media
 * buttons, etc.) and turns transport actions from any of those sources
 * back into calls MainActivity relays into the WebView.
 *
 * Bound (not just started) by MainActivity for that two-way channel, but
 * also independently started (see MainActivity.onChapterAudioReady) once
 * playback begins, so it - and the audio still playing inside the
 * WebView - survive the Activity being backgrounded or destroyed.
 */
class PlaybackService : Service() {

    interface TransportListener {
        fun onTransportPlay()
        fun onTransportPause()
        fun onTransportNext()
        fun onTransportPrevious()
        fun onTransportSeekTo(positionMs: Long)
    }

    inner class LocalBinder : Binder() {
        fun getService(): PlaybackService = this@PlaybackService
    }

    companion object {
        private const val ACTION_PLAY = "com.misao.jpaudiobookplayer.action.PLAY"
        private const val ACTION_PAUSE = "com.misao.jpaudiobookplayer.action.PAUSE"
        private const val ACTION_NEXT = "com.misao.jpaudiobookplayer.action.NEXT"
        private const val ACTION_PREVIOUS = "com.misao.jpaudiobookplayer.action.PREVIOUS"
    }

    private val binder = LocalBinder()
    private lateinit var mediaSession: MediaSessionCompat
    private var transportListener: TransportListener? = null
    private var isPlaying = false
    private var positionMs = 0L
    private var durationMs = 0L
    private var speed = 1.0f

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()

        mediaSession = MediaSessionCompat(this, "JPAudiobookPlayer").apply {
            setCallback(object : MediaSessionCompat.Callback() {
                // Covers transport-control sources outside our own notification
                // buttons too - Bluetooth headset buttons, Android Auto, Assistant.
                override fun onPlay() { transportListener?.onTransportPlay() }
                override fun onPause() { transportListener?.onTransportPause() }
                override fun onSkipToNext() { transportListener?.onTransportNext() }
                override fun onSkipToPrevious() { transportListener?.onTransportPrevious() }
                override fun onSeekTo(pos: Long) { transportListener?.onTransportSeekTo(pos) }
            })
            isActive = true
        }
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PLAY -> transportListener?.onTransportPlay()
            ACTION_PAUSE -> transportListener?.onTransportPause()
            ACTION_NEXT -> transportListener?.onTransportNext()
            ACTION_PREVIOUS -> transportListener?.onTransportPrevious()
        }
        // startForegroundService() requires a startForeground() call within
        // a few seconds of being started, regardless of why onStartCommand
        // fired - build from whatever now-playing info is already known
        // (set via updateNowPlaying(), which by construction always runs
        // before MainActivity starts this service - see
        // onChapterAudioReady()) rather than waiting for a play state.
        startForeground(NOTIFICATION_ID, buildNotification())
        return START_NOT_STICKY
    }

    fun setTransportListener(listener: TransportListener?) {
        transportListener = listener
    }

    fun updateNowPlaying(title: String, artist: String, album: String, cover: Bitmap?) {
        val metadata = MediaMetadataCompat.Builder()
            .putString(MediaMetadataCompat.METADATA_KEY_TITLE, title)
            .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, artist)
            .putString(MediaMetadataCompat.METADATA_KEY_ALBUM, album)
            .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, durationMs)
            .apply { if (cover != null) putBitmap(MediaMetadataCompat.METADATA_KEY_ALBUM_ART, cover) }
            .build()
        mediaSession.setMetadata(metadata)
        notify(buildNotification())
    }

    fun updatePlaybackState(playing: Boolean, positionSeconds: Double, durationSeconds: Double, playbackSpeed: Float) {
        isPlaying = playing
        positionMs = (positionSeconds * 1000).toLong().coerceAtLeast(0L)
        val newDurationMs = (durationSeconds * 1000).toLong().coerceAtLeast(0L)
        speed = playbackSpeed

        if (newDurationMs != durationMs) {
            durationMs = newDurationMs
            // Duration wasn't known (or was only approximate) when
            // updateNowPlaying() last ran - refresh it so the system
            // seekbar's end position matches the real chapter length.
            val existing = mediaSession.controller.metadata
            if (existing != null) {
                mediaSession.setMetadata(
                    MediaMetadataCompat.Builder(existing)
                        .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, durationMs)
                        .build()
                )
            }
        }

        mediaSession.setPlaybackState(
            PlaybackStateCompat.Builder()
                .setActions(
                    PlaybackStateCompat.ACTION_PLAY or
                        PlaybackStateCompat.ACTION_PAUSE or
                        PlaybackStateCompat.ACTION_PLAY_PAUSE or
                        PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
                        PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or
                        PlaybackStateCompat.ACTION_SEEK_TO
                )
                .setState(
                    if (playing) PlaybackStateCompat.STATE_PLAYING else PlaybackStateCompat.STATE_PAUSED,
                    positionMs,
                    if (playing) speed else 0f
                )
                .build()
        )

        if (playing) {
            startForeground(NOTIFICATION_ID, buildNotification())
        } else {
            // Demoted to a plain dismissible notification while paused,
            // not removed outright - stopSession() is what actually ends
            // the session (triple-tap back to the library in the UI).
            stopForeground(STOP_FOREGROUND_DETACH)
            notify(buildNotification())
        }
    }

    fun stopSession() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        mediaSession.isActive = false
        stopSelf()
    }

    override fun onDestroy() {
        mediaSession.release()
        super.onDestroy()
    }

    private fun notify(notification: android.app.Notification) {
        val manager = getSystemService(NotificationManager::class.java) ?: return
        manager.notify(NOTIFICATION_ID, notification)
    }

    private fun buildNotification(): android.app.Notification {
        val metadata = mediaSession.controller.metadata
        val cover = metadata?.getBitmap(MediaMetadataCompat.METADATA_KEY_ALBUM_ART)

        val contentIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val playPauseAction = if (isPlaying) {
            NotificationCompat.Action(R.drawable.ic_media_pause, "Pause", actionPendingIntent(ACTION_PAUSE))
        } else {
            NotificationCompat.Action(R.drawable.ic_media_play, "Play", actionPendingIntent(ACTION_PLAY))
        }

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(metadata?.getString(MediaMetadataCompat.METADATA_KEY_TITLE)?.takeIf { it.isNotEmpty() } ?: getString(R.string.app_name))
            .setContentText(metadata?.getString(MediaMetadataCompat.METADATA_KEY_ARTIST))
            .setSubText(metadata?.getString(MediaMetadataCompat.METADATA_KEY_ALBUM))
            .setLargeIcon(cover)
            .setContentIntent(contentIntent)
            .setOngoing(isPlaying)
            .setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addAction(NotificationCompat.Action(R.drawable.ic_media_previous, "Previous", actionPendingIntent(ACTION_PREVIOUS)))
            .addAction(playPauseAction)
            .addAction(NotificationCompat.Action(R.drawable.ic_media_next, "Next", actionPendingIntent(ACTION_NEXT)))
            .setStyle(
                MediaStyle()
                    .setMediaSession(mediaSession.sessionToken)
                    .setShowActionsInCompactView(0, 1, 2)
            )
            .build()
    }

    private fun actionPendingIntent(action: String): PendingIntent {
        val intent = Intent(this, PlaybackService::class.java).setAction(action)
        return PendingIntent.getService(
            this, action.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID, "Playback", NotificationManager.IMPORTANCE_LOW
        ).apply { description = "Audiobook playback controls" }
        val manager = getSystemService(NotificationManager::class.java)
        manager?.createNotificationChannel(channel)
    }
}
