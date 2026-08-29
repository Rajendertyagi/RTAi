import { useCallback, useEffect, useRef } from "react";
import { isServerEvent, type ClientCommand, type ServerEvent } from "../types/protocol";

interface UseChatSocket {
  connect: (folder: string) => void;
  send: (command: ClientCommand) => void;
  close: () => void;
}

// Transport abstraction: the only place that knows about WebSocket.
// Swap this hook for SSE/HTTP later without touching the UI or state.
export function useChatSocket(onEvent: (event: ServerEvent) => void): UseChatSocket {
  const wsRef = useRef<WebSocket | null>(null);
  const folderRef = useRef<string>("");
  const onEventRef = useRef(onEvent);
  const closedByUser = useRef(false);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const connect = useCallback((folder: string) => {
    folderRef.current = folder;
    closedByUser.current = false;

    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const url = folder
      ? `${scheme}://${location.host}/ws?cwd=${encodeURIComponent(folder)}`
      : `${scheme}://${location.host}/ws`;

    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (isServerEvent(data)) onEventRef.current(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      if (!closedByUser.current && folderRef.current) {
        setTimeout(() => connect(folderRef.current), 3000);
      }
    };
  }, []);

  const send = useCallback((command: ClientCommand) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(command));
    }
  }, []);

  const close = useCallback(() => {
    closedByUser.current = true;
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  useEffect(() => () => wsRef.current?.close(), []);

  return { connect, send, close };
}
