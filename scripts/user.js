// Reduce content processes (default is 8, each ~100-150MB)
user_pref("dom.ipc.processCount", 1);

// Disable GPU compositing (frees GPU memory for SD)
user_pref("layers.acceleration.disabled", true);
user_pref("gfx.webrender.all", false);

// Limit memory cache (in KB)
user_pref("browser.cache.memory.capacity", 16384);
user_pref("browser.cache.disk.capacity", 32768);

// Disable speculative loading
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.http.speculative-parallel-limit", 0);

// Disable telemetry/updates (kiosk doesn't need them)
user_pref("app.update.enabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);

// Disable session restore / crash recovery
user_pref("browser.sessionstore.enabled", false);
user_pref("browser.sessionstore.resume_from_crash", false);

// Aggressive memory release
user_pref("javascript.options.mem.gc_allocation_threshold_mb", 20);
user_pref("javascript.options.mem.high_water_mark", 32);
user_pref("browser.tabs.unloadOnLowMemory", true);
