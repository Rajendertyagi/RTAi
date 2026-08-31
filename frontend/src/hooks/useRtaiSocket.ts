import { useCallback, useEffect, useRef } from "react";
import { isServerEvent, type ClientCommand, type ServerEvent } from "../types/protocol";

interface UseRtaiSocket {
  connect: (cwd?: string) => void;
  send: (command: ClientCommand) => boolean;
  close: () => void;
  connected: boolean;
}

// Transport abstraction: the only place that knows about WebSocket.
// Reconnect fix from git 751f4b6: wsRef.current === ws guard in onclose
// prevents spawning multiple reconnect loops when connect() supersedes a socket.
export function useRtaiSocket(onEvent: (event: ServerEvent) => void): UseRtaiSocket {
  const wsRef = useRef<WebSocket | null>(null);
  const onEventRef = useRef(onEvent);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectedRef = useRef(false);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const connect = useCallback((cwd?: string) => {
    // Close any existing connection first
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    // Clear any pending reconnect timer
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const url = cwd
      ? `${scheme}://${location.host}/ws?cwd=${encodeURIComponent(cwd)}`
      : `${scheme}://${location.host}/ws`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      connectedRef.current = true;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (isServerEvent(data)) {
          onEventRef.current(data);
        }
      } catch {
        // Ignore malformed frames — documented in EVENT_PROTOCOL.md
      }
    };

    ws.onclose = (event) => {
      // Only set connected to false if this was the current websocket
      if (wsRef.current === ws) {
        connectedRef.current = false;
        wsRef.current = null;
      }
      // Reconnect if:
      // 1. We didn't intentionally close (not a normal closure from our side)
      // 2. The current wsRef still points to this socket (no newer connect() called)
      // 3. It wasn't a clean close (code 1000) or going-away (code 1001)
      const shouldReconnect =
        wsRef.current === ws &&
        !event.wasClean &&
        event.code !== 1000 &&
        event.code !== 1001;

      if (shouldReconnect) {
        // Exponential backoff: 1s, 2s, 4s, ..., max 30s
        const delay = Math.min(1000 * Math.pow(2, Math.floor(Math.random() * 5)), 30000);
        reconnectTimerRef.current = setTimeout(() => connect(cwd), delay);
      }
    };

    ws.onerror = () => {
      // Error events are followed by close; the onclose handler manages reconnect
    };
  }, []);

  const send = useCallback((command: ClientCommand): boolean => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(command));
      return true;
    }
    return false;
  }, []);

  const close = useCallback(() => {
    // Mark intentional close — prevents reconnect
    if (wsRef.current) {
      wsRef.current.close(1000, "Intentional close");
      wsRef.current = null;
      connectedRef.current = false;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      close();
    };
  }, [close]);

  return { connect, send, close, connected: connectedRef.current };
}
