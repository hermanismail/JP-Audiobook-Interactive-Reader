// Browser stand-in for the Android WebView's window.Android bridge
// (MainActivity.kt's LibraryBridge) - implements the same 12 methods
// against this server's HTTP API instead of a JavascriptInterface, so
// index.html's reader UI (gestures, karaoke highlight, presets, zen
// mode) can run unmodified in a plain browser tab. Two extra methods
// (listBooks/selectBook, below) exist only in this shim - the web
// copy's own book-switcher UI uses them; there's no Android equivalent
// since the native app only ever has one folder open at a time.
//
// The selected book persists across reloads via localStorage
// (server/public/index.html's own book-switcher writes it through
// selectBook()) - defaults to the first configured book if nothing's
// been selected yet, or if a previously-selected id no longer exists
// (e.g. config.json changed since).
(function () {
  var state = { bookId: null };
  try {
    state.bookId = localStorage.getItem('selectedBookId');
  } catch (e) {
    /* ignore */
  }

  function getJson(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status + ' for ' + url);
      return res.json();
    });
  }

  window.Android = {
    // No-op: there is no in-browser folder picker in the Android-parity
    // sense - book switching goes through listBooks()/selectBook() below
    // instead. listChapters() always reports hasFolder:true (the server's
    // config guarantees at least one library path), so this button's
    // empty-state branch in index.html never actually fires.
    pickFolder: function () {},

    listBooks: async function () {
      return JSON.stringify(await getJson('/api/books'));
    },

    selectBook: function (bookId) {
      state.bookId = bookId;
      try {
        localStorage.setItem('selectedBookId', bookId);
      } catch (e) {
        /* ignore */
      }
    },

    // Plain getter, no validation - the home screen's renderHome()
    // cross-checks this against a fresh /api/books list itself (the same
    // "still exists?" check listChapters() below does independently for
    // its own use), so this doesn't need to duplicate that here.
    currentBookId: function () {
      return state.bookId;
    },

    listChapters: async function () {
      var booksRes = await getJson('/api/books');
      var books = booksRes.books || [];
      var book = books.find(function (b) { return b.id === state.bookId; }) || books[0];
      if (!book) return JSON.stringify({ hasFolder: false, chapters: [] });
      state.bookId = book.id;
      try {
        localStorage.setItem('selectedBookId', book.id);
      } catch (e) {
        /* ignore */
      }
      var chaptersRes = await getJson('/api/books/' + book.id + '/chapters');
      return JSON.stringify({
        hasFolder: true,
        bookId: book.id,
        bookTitle: book.title,
        bookAuthor: book.author,
        chapters: chaptersRes.chapters,
      });
    },

    // Only ever called with "<base>.sync.json" in index.html.
    readTextFile: async function (fileName) {
      var base = fileName.replace(/\.sync\.json$/, '');
      var res = await fetch('/api/books/' + state.bookId + '/chapters/' + base + '/sync');
      return await res.text();
    },

    // Streaming has no "prepare/cache-copy" phase the way the Android
    // app's private-cache-copy approach needed - just fetch the ID3
    // metadata and report ready immediately.
    prepareChapterAudio: async function (base) {
      try {
        var meta = await getJson(
          '/api/books/' + state.bookId + '/chapters/' + base + '/metadata'
        );
        window.onAudioPrepareReady(base, JSON.stringify(meta));
      } catch (e) {
        window.onAudioPrepareFailed(base, e.message);
      }
    },

    // No lock-screen/MediaSession integration in this phase (the
    // browser's own Media Session API is a natural later addition) - but
    // this is still the one path that persists resume position, so it's
    // not a full no-op: a fire-and-forget PUT, same as the ~1/sec
    // throttled call site already expects (not awaited there either).
    reportPlaybackState: function (isPlaying, positionSeconds, durationSeconds, speed, chapterBase) {
      if (!state.bookId || !chapterBase) return;
      fetch('/api/books/' + state.bookId + '/last-position', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapterBase: chapterBase, positionSeconds: positionSeconds }),
      }).catch(function () {});
    },
    stopPlaybackSession: function () {},

    saveBookmark: async function (chapterBase, positionSeconds) {
      try {
        var res = await fetch('/api/books/' + state.bookId + '/bookmarks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chapterBase: chapterBase, positionSeconds: positionSeconds }),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return JSON.stringify(await res.json());
      } catch (e) {
        return JSON.stringify({ error: e.message });
      }
    },
    listBookmarksAndLastPosition: async function () {
      try {
        return JSON.stringify(
          await getJson('/api/books/' + state.bookId + '/bookmarks-and-last-position')
        );
      } catch (e) {
        return JSON.stringify({ lastPosition: null, bookmarks: [] });
      }
    },
    deleteBookmark: async function (id) {
      try {
        await fetch('/api/books/' + state.bookId + '/bookmarks/' + encodeURIComponent(id), {
          method: 'DELETE',
        });
      } catch (e) {
        /* ignore */
      }
    },

    // Text preset is a single-user, per-browser preference - localStorage
    // is a fine (and synchronous, unlike fetch) substitute for the global
    // SharedPreferences setting the Android bridge uses.
    getTextPreset: function () {
      try {
        return localStorage.getItem('textPreset') || 'A';
      } catch (e) {
        return 'A';
      }
    },
    setTextPreset: function (preset) {
      try {
        localStorage.setItem('textPreset', preset);
      } catch (e) {
        /* ignore */
      }
    },

    resolveChapterImages: async function (base) {
      var res = await getJson(
        '/api/books/' + state.bookId + '/chapters/' + base + '/images'
      );
      return JSON.stringify(res);
    },

    // Browser equivalent of hiding the status/nav bars: the Fullscreen API.
    setImmersiveMode: function (enabled) {
      if (enabled) {
        document.documentElement.requestFullscreen().catch(function () {});
      } else if (document.fullscreenElement) {
        document.exitFullscreen().catch(function () {});
      }
    },
  };

  // Real HTTP URLs (Range-capable, see server/src/routes/books.js) - the
  // web reader script uses these directly instead of Android's virtual
  // appassets.androidplatform.net endpoints, since a real Range-serving
  // file server needs none of the SAF/WebView-specific workarounds those
  // existed for (see index.html's seekToTime()/onAudioPrepareReady()).
  window.audioUrl = function (chapterBase) {
    return '/api/books/' + state.bookId + '/chapters/' + chapterBase + '/audio';
  };
  window.coverUrl = function (chapterBase) {
    return '/api/books/' + state.bookId + '/chapters/' + chapterBase + '/cover';
  };
  window.chapterImageUrl = function (fileName) {
    return '/api/books/' + state.bookId + '/images/' + fileName;
  };
})();
