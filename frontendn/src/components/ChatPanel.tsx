import { ComposerPrimitive, ThreadPrimitive } from "@assistant-ui/react";
import { useChat } from "../state/ChatContext";
import { Header } from "./Header";
import { StatusBar } from "./StatusBar";
import { AssistantMessage } from "./AssistantMessage";
import { UserMessage } from "./UserMessage";
import { ModelControls } from "./ModelControls";
import { AutoAcceptIcon, SendIcon, StopIcon } from "./Icons";

export function ChatPanel() {
  const { state, cancel, toggleAutoAccept } = useChat();

  return (
    <main className="main">
      <Header />
      <ThreadPrimitive.Root className="chat">
        <ThreadPrimitive.Viewport className="messages" autoScroll>
          <ThreadPrimitive.Empty>
            <div className="welcome-screen">
              <div className="welcome-title">RTAI Chat</div>
              <div className="welcome-subtitle">
                Enter a project folder path in the sidebar and press Enter to connect.
              </div>
            </div>
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages>
            {({ message }) =>
              message.role === "user" ? (
                <UserMessage key={message.id} />
              ) : (
                <AssistantMessage key={message.id} messageId={message.id} />
              )
            }
          </ThreadPrimitive.Messages>
          <ThreadPrimitive.ViewportFooter className="composer">
            <ComposerPrimitive.Root className="composer-card">
              <ComposerPrimitive.Input
                className="composer-input"
                id="input"
                placeholder="Ask anything... (Shift+Enter for newline)"
                rows={2}
              />
              <div className="composer-footer">
                <div className="footer-left">
                  <button
                    className={`ctrl-btn${state.autoAccept ? " is-active" : ""}`}
                    id="autoAcceptBtn"
                    title={
                      state.autoAccept
                        ? "Auto-accept permissions: ON — click to turn off"
                        : "Auto-accept permissions: OFF — click to answer prompts automatically"
                    }
                    aria-pressed={state.autoAccept}
                    type="button"
                    onClick={toggleAutoAccept}
                  >
                    <AutoAcceptIcon />
                  </button>
                </div>
                <div className="footer-right">
                  <ModelControls />
                  {state.generating ? (
                    <button
                      className="send-btn stop"
                      id="sendBtn"
                      title="Stop"
                      type="button"
                      onClick={cancel}
                    >
                      <StopIcon />
                    </button>
                  ) : (
                    <ComposerPrimitive.Send asChild>
                      <button className="send-btn" id="sendBtn" title="Send" type="button">
                        <SendIcon />
                      </button>
                    </ComposerPrimitive.Send>
                  )}
                </div>
              </div>
            </ComposerPrimitive.Root>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
      <StatusBar />
    </main>
  );
}