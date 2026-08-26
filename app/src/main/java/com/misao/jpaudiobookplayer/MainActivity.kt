package com.misao.jpaudiobookplayer

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.view.WindowInsetsControllerCompat
import androidx.documentfile.provider.DocumentFile
import androidx.webkit.WebViewAssetLoader
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileInputStream

private const val TAG = "ChapterAudio"
private const val PREFS_NAME = "jp_audiobook_player"
private const val KEY_TREE_URI = "library_tree_uri"
private const val VIRTUAL_HOST = "appassets.androidplatform.net"
private const val AUDIO_OFFSET_PATH_PREFIX = "/internal-audio-offset/"
private const val COVER_ART_PATH_PREFIX = "/internal-cover/"
// run_audiobook.py always encodes with `-b:a 320k` (CBR, no VBR flags), so
// this gives an accurate byte/time relationship for a rough offset seek -
// see serveAudioFromTime().
private const val ASSUMED_BYTES_PER_SECOND = 320_000L / 8
private const val COPY_BUFFER_BYTES = 256 * 1024

/**
 * Single-activity WebView shell. The actual player UI lives in
 * assets/web/index.html and talks back to this class through the `Android`
 * JavascriptInterface bridge (LibraryBridge, below): picking a folder,
 * listing chapters, reading small text files (sync.json / book.json), and
 * preparing a chapter's audio.
 *
 * Audio serving history (kept here for context - this took several
 * iterations to get right): the original approach hand-rolled HTTP Range
 * parsing against a live stream read directly from the SAF-picked folder.
 * That was proven byte-correct in testing but Chromium's own media
 * pipeline (FFmpegDemuxer) still failed with PIPELINE_ERROR_READ - its
 * internal expectations for a custom-scheme Range response aren't well
 * documented. Switching to copying into app-private storage and serving
 * through androidx.webkit's WebViewAssetLoader.InternalStoragePathHandler
 * fixed that - confirmed working end to end, a full chapter plays start to
 * finish with no issue.
 *
 * Next/Prev (jumping to a specific chunk) needed a second fix on top of
 * that: repositioning within an already-loaded <audio> resource proved
 * completely unreliable on this device/WebView combination, regardless of
 * mechanism - currentTime assignment, a play/seek/pause cycle, and a Media
 * Fragment (#t=) reload all reset to 0 in real on-device testing (see
 * serveAudioFromTime's doc comment for the fix). Sequential playback from
 * a resource's own byte 0 is the one thing proven solid, so jumps are now
 * built on top of that instead of fighting the broken repositioning path.
 *
 * The copy itself runs on a background thread with progress reported back
 * to JS (prepareChapterAudioAsync) rather than blocking synchronously,
 * since real chapters can run up to ~160MB and a blocking multi-second
 * copy would otherwise freeze the UI with no feedback. Only the most
 * recently opened chapter's copy is kept in internalAudioDir - others are
 * evicted before each new copy - so cache usage doesn't grow unbounded
 * across a whole book.
 *
 * NOTE: written and carefully reviewed but not compiled by me end-to-end -
 * no Android SDK/Gradle in the environment this was authored in. The
 * audio-serving logic has been iterated against real Logcat output from an
 * actual device across many rounds; the byte-offset jump mechanism
 * (serveAudioFromTime, ID3v2 detection, chapterTimeOffset tracking in the
 * JS) is the newest piece and has not yet been run on-device.
 */
class MainActivity : ComponentActivity() {

    private lateinit var webView: WebView
    private lateinit var assetLoader: WebViewAssetLoader
    private val internalAudioDir: File by lazy { File(cacheDir, "chapter-audio").apply { mkdirs() } }

    private val folderPicker = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri: Uri? ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
            getPrefs().edit().putString(KEY_TREE_URI, uri.toString()).apply()
            webView.post {
                webView.evaluateJavascript(
                    "window.onFolderPicked && window.onFolderPicked();", null
                )
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Personal-use reading app - keep the screen alive while it's open
        // rather than following the system screen timeout, since there's
        // no other user input happening while just listening/reading.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Match the system bars to the WebView's dark theme. The theme's
        // own statusBarColor/navigationBarColor items (themes.xml) cover
        // most OS versions; targetSdk 36 enforces edge-to-edge by default
        // on Android 15+, where those setters become no-ops and the bars
        // just show whatever the app draws behind them instead - since the
        // WebView background is already dark, that lands on black too. The
        // one thing that still matters on every version is icon color, so
        // force light (white) icons/text for the dark background here.
        @Suppress("DEPRECATION")
        window.statusBarColor = android.graphics.Color.BLACK
        @Suppress("DEPRECATION")
        window.navigationBarColor = android.graphics.Color.BLACK
        val insetsController = WindowInsetsControllerCompat(window, window.decorView)
        insetsController.isAppearanceLightStatusBars = false
        insetsController.isAppearanceLightNavigationBars = false

        assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler(
                "/internal-audio/",
                WebViewAssetLoader.InternalStoragePathHandler(this, internalAudioDir)
            )
            .build()

        webView = WebView(this)
        webView.settings.javaScriptEnabled = true
        webView.settings.mediaPlaybackRequiresUserGesture = false
        webView.addJavascriptInterface(LibraryBridge(), "Android")
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest
            ): WebResourceResponse? {
                val url = request.url
                if (url.path?.contains("internal-audio") == true) {
                    Log.d(TAG, "INTERCEPT ${url.lastPathSegment} range=${request.requestHeaders["Range"]}")
                }
                if (url.host == VIRTUAL_HOST && url.path?.startsWith(AUDIO_OFFSET_PATH_PREFIX) == true) {
                    return serveAudioFromTime(url)
                }
                if (url.host == VIRTUAL_HOST && url.path?.startsWith(COVER_ART_PATH_PREFIX) == true) {
                    return serveCoverArt(url)
                }
                return assetLoader.shouldInterceptRequest(url)
            }
        }
        webView.webChromeClient = object : android.webkit.WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: android.webkit.ConsoleMessage): Boolean {
                Log.d(TAG, "JS: ${consoleMessage.message()}")
                return true
            }
        }

        setContentView(webView)
        webView.loadUrl("https://$VIRTUAL_HOST/assets/web/index.html")
    }

    private fun launchFolderPicker() {
        folderPicker.launch(null)
    }

    private fun getPrefs() = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private fun savedTreeUri(): Uri? {
        val stored = getPrefs().getString(KEY_TREE_URI, null) ?: return null
        return Uri.parse(stored)
    }

    private fun libraryFolder(): DocumentFile? {
        val treeUri = savedTreeUri() ?: return null
        return DocumentFile.fromTreeUri(this, treeUri)
    }

    /**
     * Enumerates chapter_XXX.mp3 files in the picked folder, sorted
     * numerically (not lexicographically). Also opportunistically reads
     * book.json for a display title, matching the folder convention from
     * android-player-phase0-spec.md.
     */
    private fun listChaptersJson(): String {
        val folder = libraryFolder() ?: return JSONObject().apply {
            put("hasFolder", false)
            put("chapters", JSONArray())
        }.toString()

        val chapterRegex = Regex("""^(chapter_(\d+))\.mp3$""")
        val chapters = folder.listFiles()
            .mapNotNull { it.name }
            .mapNotNull { name -> chapterRegex.find(name)?.let { m -> m.groupValues[1] to m.groupValues[2].toInt() } }
            .sortedBy { it.second }
            .map { it.first }

        val bookTitle = readTextFileFromFolder("book.json")?.let { text ->
            try {
                JSONObject(text).optString("title", "")
            } catch (e: Exception) {
                ""
            }
        } ?: ""

        val result = JSONObject()
        result.put("hasFolder", true)
        result.put("bookTitle", bookTitle)
        val arr = JSONArray()
        chapters.forEach { arr.put(it) }
        result.put("chapters", arr)
        return result.toString()
    }

    private fun readTextFileFromFolder(fileName: String): String? {
        val folder = libraryFolder() ?: return null
        val target = folder.listFiles().firstOrNull { it.name == fileName } ?: return null
        return contentResolver.openInputStream(target.uri)?.use { stream ->
            stream.readBytes().toString(Charsets.UTF_8)
        }
    }

    /**
     * Copies chapter_<baseName>.mp3 from the SAF-picked folder into the
     * app's private cache directory on a background thread, reporting
     * progress back to JS via window.onAudioPrepareProgress/Ready/Failed
     * (see assets/web/index.html). Evicts any other cached chapter file
     * first, so at most one chapter's audio is duplicated on disk at a
     * time regardless of how many chapters get opened in a session.
     */
    private fun prepareChapterAudioAsync(baseName: String) {
        Thread {
            try {
                val folder = libraryFolder() ?: run {
                    notifyPrepareFailed(baseName, "no library folder saved")
                    return@Thread
                }
                val fileName = "$baseName.mp3"
                val doc = folder.listFiles().firstOrNull { it.name == fileName } ?: run {
                    notifyPrepareFailed(baseName, "$fileName not found in folder")
                    return@Thread
                }
                val destFile = File(internalAudioDir, fileName)
                val totalBytes = doc.length()

                if (destFile.exists() && destFile.length() == totalBytes) {
                    Log.d(TAG, "prepareChapterAudio: using cached copy of $fileName ($totalBytes bytes)")
                    notifyPrepareReady(baseName, metadataJsonFor(destFile))
                    return@Thread
                }

                internalAudioDir.listFiles()?.forEach { f ->
                    if (f.name != fileName) {
                        val deleted = f.delete()
                        Log.d(TAG, "evicted cached ${f.name} (deleted=$deleted)")
                    }
                }

                val copyStart = System.currentTimeMillis()
                var copiedBytes = 0L
                var lastReportedPercent = -1

                val opened = contentResolver.openInputStream(doc.uri)?.use { input ->
                    destFile.outputStream().use { output ->
                        val buffer = ByteArray(COPY_BUFFER_BYTES)
                        while (true) {
                            val read = input.read(buffer)
                            if (read <= 0) break
                            output.write(buffer, 0, read)
                            copiedBytes += read
                            val percent = if (totalBytes > 0) ((copiedBytes * 100) / totalBytes).toInt() else 100
                            if (percent != lastReportedPercent) {
                                lastReportedPercent = percent
                                notifyPrepareProgress(baseName, percent)
                            }
                        }
                    }
                    true
                } ?: false

                if (!opened) {
                    notifyPrepareFailed(baseName, "could not open input stream")
                    return@Thread
                }

                Log.d(
                    TAG,
                    "prepareChapterAudio: copied $fileName ($copiedBytes bytes) in " +
                        "${System.currentTimeMillis() - copyStart}ms"
                )
                notifyPrepareReady(baseName, metadataJsonFor(destFile))
            } catch (e: Exception) {
                Log.e(TAG, "prepareChapterAudio failed for $baseName", e)
                notifyPrepareFailed(baseName, e.message ?: "unknown error")
            }
        }.start()
    }

    /**
     * Serves chapter_<baseName>.mp3 (from the already-copied internal cache
     * copy) starting from an approximate byte offset for the given chapter
     * time, as a plain sequential 200 response - not a 206/Range response.
     * This is the fix for Next/Prev: repositioning within an
     * already-loaded <audio> resource (via currentTime assignment, via a
     * play/seek/pause cycle, and via a Media Fragment reload) all proved to
     * reset to 0 in testing, regardless of mechanism - see the extensive
     * Logcat investigation this was built from. But sequential playback of
     * a resource from ITS OWN byte 0 has been proven completely reliable
     * (a full chapter plays start to finish without issue). So a "jump" is
     * now just a fresh load of a virtual resource that starts at the
     * target position and presents itself to the browser as if THAT were
     * byte 0 - sidestepping the broken repositioning path entirely rather
     * than continuing to chase it.
     *
     * Byte offset is only approximate (chapters are CBR-encoded at a known
     * bitrate, but this doesn't land on an exact frame boundary) - MP3
     * decoders are self-synchronizing and can find the next valid frame
     * from any starting byte, so this is expected to land within a
     * fraction of a second of the true target, which is fine given chunks
     * are generally several seconds long.
     */
    private fun serveAudioFromTime(url: Uri): WebResourceResponse {
        val remainder = url.path!!.removePrefix(AUDIO_OFFSET_PATH_PREFIX)
        val parts = remainder.split("/")
        if (parts.size < 2) return notFound()
        val fileName = parts[0]
        val timeSeconds = parts[1].toDoubleOrNull() ?: 0.0

        val file = File(internalAudioDir, fileName)
        if (!file.exists()) {
            Log.w(TAG, "serveAudioFromTime: $fileName not found in cache")
            return notFound()
        }

        val headerSize = detectId3v2HeaderSize(file)
        val rawOffset = headerSize + (timeSeconds * ASSUMED_BYTES_PER_SECOND).toLong()
        val offset = rawOffset.coerceIn(0L, file.length())
        val remainingLength = file.length() - offset

        Log.d(
            TAG,
            "serveAudioFromTime: $fileName time=$timeSeconds id3HeaderSize=$headerSize " +
                "offset=$offset remainingLength=$remainingLength fileLength=${file.length()}"
        )

        val stream = FileInputStream(file)
        if (offset > 0) {
            stream.channel.position(offset)
        }

        val headers = mapOf("Content-Length" to remainingLength.toString())
        return WebResourceResponse("audio/mpeg", null, 200, "OK", headers, stream)
    }

    /**
     * Returns the byte length of a leading ID3v2 tag, or 0 if there isn't
     * one. The cached copy is the fully-tagged output (title, cover art,
     * etc. via mp3_metadata.py), so byte 0 is NOT necessarily time 0 - an
     * embedded cover image alone can be tens of KB before the actual audio
     * frames start, which would silently throw off every offset
     * computation if unaccounted for.
     */
    private fun detectId3v2HeaderSize(file: File): Long {
        return try {
            FileInputStream(file).use { stream ->
                val header = ByteArray(10)
                if (stream.read(header) < 10) return 0L
                if (header[0] != 'I'.code.toByte() || header[1] != 'D'.code.toByte() || header[2] != '3'.code.toByte()) {
                    return 0L
                }
                // Synchsafe 4-byte size: only the low 7 bits of each byte count.
                val size = ((header[6].toInt() and 0x7F) shl 21) or
                    ((header[7].toInt() and 0x7F) shl 14) or
                    ((header[8].toInt() and 0x7F) shl 7) or
                    (header[9].toInt() and 0x7F)
                10L + size
            }
        } catch (e: Exception) {
            Log.e(TAG, "detectId3v2HeaderSize failed for ${file.name}", e)
            0L
        }
    }

    private fun notFound(): WebResourceResponse {
        return WebResourceResponse(
            "text/plain", "utf-8", 404, "Not Found", emptyMap(),
            ByteArrayInputStream(ByteArray(0))
        )
    }

    private fun notifyPrepareProgress(baseName: String, percent: Int) {
        webView.post {
            webView.evaluateJavascript(
                "window.onAudioPrepareProgress && window.onAudioPrepareProgress(${JSONObject.quote(baseName)}, $percent);",
                null
            )
        }
    }

    private fun notifyPrepareReady(baseName: String, metadataJson: String) {
        webView.post {
            webView.evaluateJavascript(
                "window.onAudioPrepareReady && window.onAudioPrepareReady(${JSONObject.quote(baseName)}, ${JSONObject.quote(metadataJson)});",
                null
            )
        }
    }

    /**
     * Reads TIT2/TPE1/TALB and whether an APIC (cover) frame is present from
     * the given file's ID3v2 tag, as a JSON string for the JS side
     * (window.onAudioPrepareReady). Parsed straight from the just-copied
     * cache file rather than the original SAF document - it's already local
     * and this avoids a second SAF round trip.
     */
    private fun metadataJsonFor(file: File): String {
        val tag = parseId3Tag(file)
        return JSONObject().apply {
            put("title", tag.title ?: "")
            put("artist", tag.artist ?: "")
            put("album", tag.album ?: "")
            put("hasCover", tag.coverBytes != null)
        }.toString()
    }

    /**
     * Serves the embedded cover image (ID3v2 APIC frame) for
     * chapter_<baseName>.mp3 out of the internal cache copy, re-parsing the
     * tag on each request rather than caching the decoded bytes - at
     * ~1-2MB and once per chapter open this is cheap enough that the extra
     * bookkeeping isn't worth it.
     */
    private fun serveCoverArt(url: Uri): WebResourceResponse {
        val fileName = url.path!!.removePrefix(COVER_ART_PATH_PREFIX)
        val file = File(internalAudioDir, fileName)
        if (!file.exists()) return notFound()

        val tag = parseId3Tag(file)
        val coverBytes = tag.coverBytes ?: return notFound()
        return WebResourceResponse(
            tag.coverMime ?: "image/jpeg", null, 200, "OK", emptyMap(),
            ByteArrayInputStream(coverBytes)
        )
    }

    private data class Id3Tag(
        val title: String? = null,
        val artist: String? = null,
        val album: String? = null,
        val coverMime: String? = null,
        val coverBytes: ByteArray? = null
    )

    /**
     * Minimal manual ID3v2.2/2.3/2.4 frame reader - just enough to pull
     * TIT2/TPE1/TPE2/TALB text and an APIC/PIC cover image, the same
     * hand-rolled-parsing style already used by detectId3v2HeaderSize
     * above (no bundled ID3 library). Frame *size* encoding differs by
     * version: v2.4 sizes are synchsafe like the tag header, v2.3 sizes are
     * plain big-endian, and v2.2 uses 3-byte IDs with 3-byte plain sizes -
     * getting this wrong silently misaligns every frame after the first.
     */
    private fun parseId3Tag(file: File): Id3Tag {
        return try {
            FileInputStream(file).use { stream ->
                val header = ByteArray(10)
                if (readFully(stream, header) < 10) return Id3Tag()
                if (header[0] != 'I'.code.toByte() || header[1] != 'D'.code.toByte() || header[2] != '3'.code.toByte()) {
                    return Id3Tag()
                }
                val majorVersion = header[3].toInt()
                val tagSize = synchsafeInt(header[6], header[7], header[8], header[9])
                val body = ByteArray(tagSize)
                readFully(stream, body)

                var title: String? = null
                var artist: String? = null
                var album: String? = null
                var coverMime: String? = null
                var coverBytes: ByteArray? = null

                var pos = 0
                val idLen = if (majorVersion == 2) 3 else 4
                while (pos + idLen <= body.size) {
                    val idBytes = body.copyOfRange(pos, pos + idLen)
                    val isValidId = idBytes.all { b ->
                        (b >= 'A'.code.toByte() && b <= 'Z'.code.toByte()) ||
                            (b >= '0'.code.toByte() && b <= '9'.code.toByte())
                    }
                    if (!isValidId) break
                    pos += idLen

                    val frameSize: Int
                    if (majorVersion == 2) {
                        if (pos + 3 > body.size) break
                        frameSize = ((body[pos].toInt() and 0xFF) shl 16) or
                            ((body[pos + 1].toInt() and 0xFF) shl 8) or
                            (body[pos + 2].toInt() and 0xFF)
                        pos += 3
                    } else {
                        if (pos + 6 > body.size) break
                        frameSize = if (majorVersion == 4) {
                            synchsafeInt(body[pos], body[pos + 1], body[pos + 2], body[pos + 3])
                        } else {
                            ((body[pos].toInt() and 0xFF) shl 24) or
                                ((body[pos + 1].toInt() and 0xFF) shl 16) or
                                ((body[pos + 2].toInt() and 0xFF) shl 8) or
                                (body[pos + 3].toInt() and 0xFF)
                        }
                        pos += 4 + 2 // size + 2 flag bytes
                    }
                    if (frameSize < 0 || pos + frameSize > body.size) break
                    val frameData = body.copyOfRange(pos, pos + frameSize)
                    pos += frameSize

                    when (val frameId = String(idBytes, Charsets.US_ASCII)) {
                        "TIT2" -> title = decodeId3Text(frameData)
                        "TPE1", "TPE2" -> if (artist.isNullOrEmpty()) artist = decodeId3Text(frameData)
                        "TALB" -> album = decodeId3Text(frameData)
                        "APIC", "PIC" -> {
                            val parsed = decodeApicFrame(frameData, isV22 = frameId == "PIC")
                            if (parsed != null) {
                                coverMime = parsed.first
                                coverBytes = parsed.second
                            }
                        }
                    }
                }
                Id3Tag(title, artist, album, coverMime, coverBytes)
            }
        } catch (e: Exception) {
            Log.e(TAG, "parseId3Tag failed for ${file.name}", e)
            Id3Tag()
        }
    }

    private fun readFully(stream: java.io.InputStream, buffer: ByteArray): Int {
        var total = 0
        while (total < buffer.size) {
            val read = stream.read(buffer, total, buffer.size - total)
            if (read <= 0) break
            total += read
        }
        return total
    }

    private fun synchsafeInt(b0: Byte, b1: Byte, b2: Byte, b3: Byte): Int {
        return ((b0.toInt() and 0x7F) shl 21) or
            ((b1.toInt() and 0x7F) shl 14) or
            ((b2.toInt() and 0x7F) shl 7) or
            (b3.toInt() and 0x7F)
    }

    // ID3 text frames are padded with trailing NUL bytes, not spaces - strip
    // those via the Char(0) constructor rather than a raw escape literal so the
    // literal byte never ends up embedded in this source file.
    private val ID3_TEXT_PAD = Char(0)

    private fun decodeId3Text(frameData: ByteArray): String {
        if (frameData.isEmpty()) return ""
        val encoding = frameData[0].toInt()
        val textBytes = frameData.copyOfRange(1, frameData.size)
        val raw = when (encoding) {
            1 -> String(textBytes, Charsets.UTF_16) // UTF-16 with BOM
            2 -> String(textBytes, Charsets.UTF_16BE)
            3 -> String(textBytes, Charsets.UTF_8)
            else -> String(textBytes, Charsets.ISO_8859_1)
        }
        return raw.trimEnd(ID3_TEXT_PAD)
    }

    /** APIC (v2.3/2.4) has a MIME string; the older PIC (v2.2) has a 3-char image format code instead. */
    private fun decodeApicFrame(frameData: ByteArray, isV22: Boolean): Pair<String, ByteArray>? {
        if (frameData.isEmpty()) return null
        var pos = 0
        pos += 1 // text encoding byte
        val mime: String
        if (isV22) {
            if (pos + 3 > frameData.size) return null
            val fmt = String(frameData, pos, 3, Charsets.US_ASCII)
            pos += 3
            mime = if (fmt.equals("PNG", ignoreCase = true)) "image/png" else "image/jpeg"
        } else {
            var nul = pos
            while (nul < frameData.size && frameData[nul].toInt() != 0) nul++
            if (nul >= frameData.size) return null
            mime = String(frameData, pos, nul - pos, Charsets.US_ASCII)
            pos = nul + 1
        }
        if (pos >= frameData.size) return null
        pos += 1 // picture type byte

        // Description string, null-terminated (2 bytes if the text encoding is a UTF-16 variant).
        val encoding = frameData[0].toInt()
        pos = if (encoding == 1 || encoding == 2) {
            var i = pos
            while (i + 1 < frameData.size && !(frameData[i].toInt() == 0 && frameData[i + 1].toInt() == 0)) i += 2
            i + 2
        } else {
            var i = pos
            while (i < frameData.size && frameData[i].toInt() != 0) i++
            i + 1
        }
        if (pos < 0 || pos > frameData.size) return null
        return mime to frameData.copyOfRange(pos, frameData.size)
    }

    private fun notifyPrepareFailed(baseName: String, reason: String) {
        webView.post {
            webView.evaluateJavascript(
                "window.onAudioPrepareFailed && window.onAudioPrepareFailed(${JSONObject.quote(baseName)}, ${JSONObject.quote(reason)});",
                null
            )
        }
    }

    /** JS bridge exposed as `window.Android` in assets/web/index.html. */
    inner class LibraryBridge {
        @JavascriptInterface
        fun pickFolder() {
            runOnUiThread { launchFolderPicker() }
        }

        @JavascriptInterface
        fun listChapters(): String = listChaptersJson()

        @JavascriptInterface
        fun readTextFile(fileName: String): String = readTextFileFromFolder(fileName) ?: ""

        @JavascriptInterface
        fun prepareChapterAudio(baseName: String) {
            prepareChapterAudioAsync(baseName)
        }
    }
}
