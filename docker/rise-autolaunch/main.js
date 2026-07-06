// RISE autolaunch cold-cache watchdog — QuBins 2.1-xl-rise flavor only.
//
// Problem (QuBins#108): RISE 5.7.1 runs its autolaunch exactly once, at
// nbextension load, via
//     configLoaded().then(...).then(autoLaunch)      (rise main.js ~L1353)
// and autoLaunch() only enters the slideshow if is_slideshow(notebook) is
// true *at that instant* (main.js L393/L172). On a cold cache the RISE
// extension can win the race before the notebook's cells are populated,
// so is_slideshow() is false and the one-shot, no-retry autolaunch is
// silently skipped — the first-time visitor lands in a plain notebook. A
// reload (now warm) wins the race and presents fine.
//
// This watchdog re-checks a short beat after `notebook_loaded` and enters
// the slideshow if — and only if — RISE itself would have, and we are not
// already presenting. It is idempotent: a no-op on every healthy load,
// and it only ever *enters* (never exits) the slideshow.
//
// Pairs with the image-level autolaunch default (QuBins#107,
// etc/jupyter/nbconfig/rise.json = {"autolaunch": true}); per-notebook
// `rise`/`livereveal` metadata still overrides, including opt-out.

define(['base/js/namespace', 'base/js/events'], function (Jupyter, events) {
  'use strict';

  var FIRST_DELAY_MS = 2000;   // let cold assets + cell rendering settle
  var RETRY_MS = 1500;         // RISE may not have registered its action yet
  var MAX_TRIES = 4;
  var ACTION = 'RISE:slideshow';

  function actionsMgr() {
    var nb = Jupyter.notebook;
    return nb && nb.keyboard_manager && nb.keyboard_manager.actions;
  }

  // RISE swaps the notebook DOM for a visible `.reveal` container while
  // presenting. Use that as the external signal so we never re-toggle
  // (RISE:slideshow's handler is a toggle) a healthy load back OUT of the
  // slideshow.
  function inRevealMode() {
    var el = document.querySelector('.reveal');
    return !!(el && el.offsetParent !== null);
  }

  // Faithful to RISE's config precedence: notebook `rise.autolaunch` wins,
  // then `livereveal.autolaunch`, else the image default (true, from
  // etc/jupyter/nbconfig/rise.json in this -rise flavor). This respects an
  // explicit per-notebook opt-out (autolaunch: false).
  function autolaunchEnabled() {
    var md = (Jupyter.notebook && Jupyter.notebook.metadata) || {};
    var r = md.rise || {}, l = md.livereveal || {};
    if (typeof r.autolaunch === 'boolean') return r.autolaunch;
    if (typeof l.autolaunch === 'boolean') return l.autolaunch;
    return true;
  }

  // Mirror RISE's is_slideshow(): true iff some cell is a slide/subslide.
  function isSlideshow() {
    var nb = Jupyter.notebook;
    if (!nb) return false;
    return nb.get_cells().some(function (c) {
      var st = (c.metadata.slideshow || {}).slide_type;
      return st === 'slide' || st === 'subslide';
    });
  }

  function attempt(tries) {
    if (inRevealMode()) return;                          // already presenting
    if (!autolaunchEnabled() || !isSlideshow()) return;  // RISE wouldn't autostart this notebook
    var mgr = actionsMgr();
    var ready = mgr && (mgr.exists ? mgr.exists(ACTION) : true);
    if (ready) {
      try {
        mgr.call(ACTION);
      } catch (e) {
        console.warn('[rise-autolaunch] rescue failed:', e);
      }
      return;
    }
    // RISE not registered yet — retry a few times before giving up.
    if (tries < MAX_TRIES) {
      setTimeout(function () { attempt(tries + 1); }, RETRY_MS);
    }
  }

  function schedule() {
    setTimeout(function () { attempt(1); }, FIRST_DELAY_MS);
  }

  function load_ipython_extension() {
    // If the notebook already loaded before we initialised (we missed the
    // event), schedule right away; otherwise wait for the load event.
    if (Jupyter.notebook && Jupyter.notebook._fully_loaded) {
      schedule();
    }
    events.on('notebook_loaded.Notebook', schedule);
  }

  return { load_ipython_extension: load_ipython_extension };
});
