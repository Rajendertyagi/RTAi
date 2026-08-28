import { useChat } from "../state/ChatContext";
import { useAutoScroll } from "../hooks/useAutoScroll";
import { Header } from "./Header";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";
import { MessageBubble } from "./MessageBubble";

export function ChatPanel() {
  const { state } = useChat();
  const messagesRef = useAutoScroll<HTMLDivElement>(state.messages);

  return (
    <main className="main">
      <Header />
      <div className="chat">
        <div className="messages" id="messages" ref={messagesRef}>
          {state.messages.length === 0 ? (
            <div className="message agent">
              <div className="avatar">AI</div>
              <div className="bubble">Enter a project folder path and press Enter to connect.</div>
            </div>
          ) : (
            state.messages.map((m) => <MessageBubble key={m.id} message={m} />)
          )}
        </div>
        <Composer />
      </div>
      <StatusBar />
    </main>
  );
}
