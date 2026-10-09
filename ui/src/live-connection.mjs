import {
  createStore,
  applySnapshot,
  applyUpdate,
  applyFeedStatus,
} from "../live/live.mjs";
// Keep reception ordering in the tested store; publish immutable snapshots to Svelte.
export function connectLive(onChange) {
  const store = createStore(),
    abort = new AbortController();
  let stopped = false,
    pending = null,
    source,
    retry,
    throttle;
  let connected = false,
    initialReceived = false,
    status = "Connecting";
  function publish() {
    if (!stopped)
      onChange({
        vessels: [...store.vessels.values()],
        feed: { ...store.feed },
        connected,
        initialReceived,
        status,
      });
  }
  function changed() {
    if (!throttle)
      throttle = setTimeout(() => {
        throttle = null;
        publish();
      }, 120);
  }
  function connection(value, description) {
    connected = value;
    status = description;
    changed();
  }
  async function snapshot() {
    if (pending) return pending;
    pending = (async () => {
      const response = await fetch("/api/v1/vessels", {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: abort.signal,
      });
      if (!response.ok) throw new Error("Snapshot unavailable");
      const payload = await response.json();
      if (stopped) return;
      if (applySnapshot(store, payload)) {
        initialReceived = true;
        changed();
      } else if (!initialReceived) throw new Error("Invalid snapshot");
    })().finally(() => {
      pending = null;
    });
    return pending;
  }
  function parse(event) {
    try {
      return JSON.parse(event.data);
    } catch {
      return null;
    }
  }
  function events() {
    source = new EventSource("/api/v1/events");
    source.onopen = () => {
      connection(true, "Shared service connected");
      if (!initialReceived) snapshot().catch(() => {});
    };
    source.onerror = () => connection(false, "Reconnecting");
    source.addEventListener("snapshot", (event) => {
      if (applySnapshot(store, parse(event))) {
        initialReceived = true;
        connection(true, "Shared service connected");
      }
    });
    source.addEventListener("update", (event) => {
      const payload = parse(event),
        previous = store.sequence,
        result = applyUpdate(store, payload);
      if (result === "resync") {
        snapshot().catch(() => {});
        return;
      }
      if (result === "applied") {
        initialReceived = true;
        connection(true, "Shared service connected");
        if (payload.sequence > previous + 1) snapshot().catch(() => {});
      }
    });
    for (const type of ["status", "heartbeat"])
      source.addEventListener(type, (event) => {
        const payload = parse(event);
        if (!payload) return;
        if (
          payload.stream_id &&
          store.streamId &&
          payload.stream_id !== store.streamId
        ) {
          snapshot().catch(() => {});
          return;
        }
        applyFeedStatus(store, payload);
        initialReceived = true;
        connection(true, "Shared service connected");
      });
  }
  (async () => {
    try {
      await snapshot();
    } catch {
      connection(false, "Service unavailable");
    }
    if (stopped) return;
    events();
    retry = setInterval(() => {
      if (!initialReceived) snapshot().catch(() => {});
    }, 10000);
  })();
  return {
    store,
    destroy() {
      stopped = true;
      abort.abort();
      source?.close();
      clearInterval(retry);
      clearTimeout(throttle);
    },
  };
}
