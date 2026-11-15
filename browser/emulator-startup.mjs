// EmulatorJS 4.2.3 reads saved core/thread settings before its configured defaults.
export function configureEmulatorStartup(environment) {
  const {navigator} = environment;
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  const threads = !ios && typeof environment.SharedArrayBuffer === 'function';
  environment.EJS_threads = threads;
  environment.EJS_defaultOptions = {...environment.EJS_defaultOptions,
    ejs_threads: threads ? 'enabled' : 'disabled'};
  if (!threads) {
    try {
      const key = `ejs-${environment.EJS_gameID || 1}-n64-${environment.EJS_gameName}-settings`;
      const saved = JSON.parse(environment.localStorage.getItem(key));
      if (saved?.settings && (saved.settings.ejs_threads === 'enabled' ||
          ios && saved.settings.retroarch_core === 'mupen64plus_next')) {
        saved.settings.ejs_threads = 'disabled';
        if (ios && saved.settings.retroarch_core === 'mupen64plus_next') {
          saved.settings.retroarch_core = 'parallel_n64';
        }
        environment.localStorage.setItem(key, JSON.stringify(saved));
      }
    } catch {
      // Browser privacy settings can make optional preference storage unavailable.
    }
  }
}
