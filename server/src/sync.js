import { WebSocketServer } from 'ws';

// Device-priority model (see CLAUDE.md's "device priority rules" for the
// full reasoning this implements). Only two slots ever matter:
//   activeDeviceId/activeDeviceKind/activeDeviceName - whoever's currently
//     active (a tv-player or a normal player.html instance).
//   idleTvId/idleTvName - at most ONE tv-player allowed to sit idle-but-
//     present at a time. tv-player is the only device kind that ever gets
//     an idle state instead of being killed outright.
// This app is still explicitly single-user/LAN-scoped (see the
// last_position known-limitation note in CLAUDE.md), so no auth here.
const clients = new Map(); // ws -> { deviceId, deviceName, deviceKind, role }
const playerState = new Map(); // deviceId -> latest state payload

let activeDeviceId = null;
let activeDeviceKind = null;
let activeDeviceName = null;
let idleTvId = null;
let idleTvName = null;

function send(ws, payload) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(payload));
}

function broadcast(payload, exclude) {
  for (const ws of clients.keys()) {
    if (ws !== exclude) send(ws, payload);
  }
}

function sendToDevice(deviceId, payload) {
  for (const [ws, info] of clients.entries()) {
    if (info.deviceId === deviceId) send(ws, payload);
  }
}

// Shape consumed directly by remote.html: at most one active device and at
// most one idle (always tv) device, never a longer generic list - matches
// the "maximum two devices" rule exactly, so the client doesn't need to
// re-derive it from a raw connection list.
function devicesSnapshot() {
  return {
    type: 'devices',
    active: activeDeviceId
      ? { deviceId: activeDeviceId, deviceName: activeDeviceName, deviceKind: activeDeviceKind }
      : null,
    idleTv: idleTvId ? { deviceId: idleTvId, deviceName: idleTvName } : null,
  };
}

function broadcastDevices() {
  broadcast(devicesSnapshot());
}

// Runs whenever a device with role:'player' connects (tv-player.html or
// player.html) - claims active status immediately, before any content is
// necessarily loaded, and displaces whatever was there before:
//   new TV vs active/idle TV (different id) -> old TV evicted outright
//     (only one TV identity ever tracked; if it happened to be active it
//     gets `deactivate` same as any displaced TV, and either way is no
//     longer tracked as the idle slot afterward - it's already showing
//     its own idle screen, so no message is needed for the merely-idle
//     case, just forgetting it server-side).
//   new TV vs active normal player           -> old player `killed`
//   new normal player vs active TV           -> TV `deactivate`, becomes
//     the tracked idle TV
//   new normal player vs active normal player -> old player `killed`
// A pre-existing idle TV unrelated to this specific transition (e.g. a
// second normal player displacing a first, while some earlier TV is still
// idle from before) is left untouched - eviction of the idle slot only
// happens when a NEW TV itself connects.
function claimActive(deviceId, deviceKind, deviceName) {
  const isTv = deviceKind === 'tv';

  if (isTv) {
    // Whether this is a brand-new TV evicting a *different* idle one, or
    // the previously-idle TV itself becoming active again (switchActive/
    // continueOnDevice) - either way it can't be both active and the
    // tracked idle slot afterward, so always clear rather than only when
    // the ids differ.
    idleTvId = null;
    idleTvName = null;
    if (activeDeviceId && activeDeviceId !== deviceId) {
      if (activeDeviceKind === 'tv') {
        sendToDevice(activeDeviceId, { type: 'command', action: 'deactivate' });
      } else {
        sendToDevice(activeDeviceId, { type: 'command', action: 'killed' });
      }
      playerState.delete(activeDeviceId);
    }
    activeDeviceId = deviceId;
    activeDeviceKind = 'tv';
    activeDeviceName = deviceName;
  } else {
    if (activeDeviceId && activeDeviceId !== deviceId) {
      if (activeDeviceKind === 'tv') {
        sendToDevice(activeDeviceId, { type: 'command', action: 'deactivate' });
        idleTvId = activeDeviceId;
        idleTvName = activeDeviceName;
      } else {
        sendToDevice(activeDeviceId, { type: 'command', action: 'killed' });
      }
      playerState.delete(activeDeviceId);
    }
    activeDeviceId = deviceId;
    activeDeviceKind = deviceKind;
    activeDeviceName = deviceName;
  }

  broadcastDevices();
}

// TEMPORARY - kept from the earlier single-active-device design, still
// useful for inspecting the live registry while rebuilding on top of it.
export function debugSnapshot() {
  return {
    activeDeviceId,
    activeDeviceKind,
    activeDeviceName,
    idleTvId,
    idleTvName,
    playerStateKeys: Array.from(playerState.keys()),
    clients: Array.from(clients.values()).map((info) => ({ ...info })),
  };
}

export function attachSyncServer(httpServer) {
  const wss = new WebSocketServer({ server: httpServer, path: '/ws' });

  wss.on('connection', (ws) => {
    // Without this, an unhandled 'error' event on a socket (a flaky mobile
    // connection dropping mid-write, switching networks, etc.) is fatal to
    // the whole Node process by default.
    ws.on('error', () => {});

    ws.on('message', (raw) => {
      let msg;
      try {
        msg = JSON.parse(raw.toString());
      } catch {
        return;
      }

      if (msg.type === 'hello') {
        const info = {
          deviceId: msg.deviceId,
          deviceName: msg.deviceName || 'Unknown device',
          deviceKind: msg.deviceKind || 'unknown',
          role: msg.role === 'player' ? 'player' : 'controller',
        };
        clients.set(ws, info);

        // Bring the new client up to date immediately, rather than making
        // it wait for the next natural broadcast.
        send(ws, devicesSnapshot());
        if (activeDeviceId && playerState.has(activeDeviceId)) {
          send(ws, playerState.get(activeDeviceId));
        }

        // library.html/chapter.html/remote.html connect as role:'controller'
        // and never claim anything, per "this page won't qualify the
        // device/browser to be listed as available device."
        if (info.role === 'player') {
          claimActive(info.deviceId, info.deviceKind, info.deviceName);
        }
        return;
      }

      if (msg.type === 'state') {
        const info = clients.get(ws);
        if (!info) return;
        const payload = { ...msg, deviceId: info.deviceId, deviceName: info.deviceName, deviceKind: info.deviceKind };
        playerState.set(info.deviceId, payload);
        // Only the currently-active device's state is meaningful to relay.
        if (info.deviceId === activeDeviceId) broadcast(payload, ws);
        return;
      }

      if (msg.type === 'command') {
        // chapter.html's "Switch to [idle device]" pill - just hands over
        // active status to the tracked idle TV. No content follows; the
        // user separately picks continue/chapter/bookmark afterward,
        // which arrives as a normal `load` below, by then targeting the
        // now-active device.
        if (msg.action === 'switchActive') {
          const targetId = msg.targetDeviceId;
          if (!targetId || targetId !== idleTvId) return; // only a tracked idle TV can be woken this way
          claimActive(targetId, 'tv', idleTvName);
          return;
        }

        // remote.html's "Continue playing on [Device]" pill - same idea,
        // but also carries the currently-active device's last known
        // book/chapter/position over to the newly-activated TV
        // automatically, since the whole point is "move what's already
        // playing," not choosing something new.
        if (msg.action === 'continueOnDevice') {
          const targetId = msg.targetDeviceId;
          if (!targetId || targetId !== idleTvId) return;
          const carryState = playerState.get(activeDeviceId);
          claimActive(targetId, 'tv', idleTvName);
          if (carryState && carryState.bookId && carryState.chapterBase) {
            sendToDevice(targetId, {
              type: 'command',
              action: 'load',
              targetDeviceId: targetId,
              bookId: carryState.bookId,
              chapterBase: carryState.chapterBase,
              positionSeconds: carryState.position || 0,
            });
          }
          return;
        }

        // remote.html's "Playing on [TV]" pill, clicked to manually send
        // an active tv-player back to its own idle screen - the one case
        // where a device voluntarily leaves the active slot without
        // anything else claiming it. Only ever valid for the CURRENT
        // active device, and only when it's a tv-player (a normal player
        // has no idle state to return to - it can only be killed by
        // something else claiming active, never self-idled).
        if (msg.action === 'deactivateTv') {
          const targetId = msg.targetDeviceId;
          if (!targetId || targetId !== activeDeviceId || activeDeviceKind !== 'tv') return;
          sendToDevice(targetId, { type: 'command', action: 'deactivate' });
          idleTvId = targetId;
          idleTvName = activeDeviceName;
          activeDeviceId = null;
          activeDeviceKind = null;
          activeDeviceName = null;
          playerState.delete(targetId);
          broadcastDevices();
          return;
        }

        // Every other command (load targeting the active device with a
        // freshly-chosen chapter, playPause/seek/next/prev/nextChapter/
        // prevChapter/setPreset/setTheme/setVolume/toggleZen) just relays
        // to whichever device is named or, if none is, whoever's active.
        const targetId = msg.targetDeviceId || activeDeviceId;
        if (!targetId) return;
        sendToDevice(targetId, { ...msg, targetDeviceId: targetId });
        return;
      }
    });

    ws.on('close', () => {
      clients.delete(ws);
      // Deliberately no activeDeviceId/idleTvId cleanup here - a device's
      // slot is only ever reassigned by another device explicitly
      // claiming it (claimActive above), never by a disconnect. This
      // matters concretely: the Player/Remote navigation is a same-tab
      // page unload, which closes this exact socket as a side effect -
      // clearing state on close would erase what was just playing right
      // as the user switches to Remote to check on it.
    });
  });
}
