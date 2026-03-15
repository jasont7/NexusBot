import { useEffect, useRef, useState } from 'preact/hooks';
import { apiFetch, chatStream } from '../api';

type Message = {
  role: 'user' | 'assistant' | 'tool' | 'progress' | 'error';
  content: string;
  timestamp?: string;
};

function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) =>
    `<pre><code>${code}</code></pre>`);
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="text-accent underline">$1</a>');
  // Line breaks
  html = html.replace(/\n/g, '<br>');
  return html;
}

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [typing, setTyping] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    apiFetch<{ role: string; content: string; timestamp?: string }[]>('/chat/history')
      .then((history) => {
        setMessages(history.map((m) => ({ ...m, role: m.role as Message['role'] })));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, typing]);

  function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setTyping('nanobot is thinking...');

    chatStream(text, {
      onTool(content) {
        setTyping(content);
      },
      onProgress(content) {
        setMessages((prev) => [...prev, { role: 'progress', content }]);
      },
      onMessage(content) {
        setMessages((prev) => [...prev, { role: 'assistant', content }]);
      },
      onError(content) {
        setMessages((prev) => [...prev, { role: 'error', content }]);
      },
      onDone() {
        setBusy(false);
        setTyping('');
      },
    });
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div class="flex flex-col h-screen">
      {/* Messages */}
      <div class="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <ChatBubble key={i} msg={m} />
        ))}
        {typing && (
          <div class="text-xs text-text-dim italic px-3 py-1.5 border border-dashed border-border rounded">
            {typing}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div class="border-t border-border p-3 bg-surface">
        <div class="flex gap-2 max-w-4xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onInput={(e) => setInput((e.target as HTMLTextAreaElement).value)}
            onKeyDown={onKeyDown}
            placeholder="Message nanobot..."
            rows={1}
            class="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text resize-none focus:outline-none focus:border-accent"
            style={{ minHeight: '38px', maxHeight: '120px' }}
            disabled={busy}
          />
          <button
            onClick={send}
            disabled={busy || !input.trim()}
            class="px-4 py-2 bg-accent text-bg font-medium rounded-lg text-sm disabled:opacity-40 hover:bg-accent/80 transition-colors"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function ChatBubble({ msg }: { msg: Message }) {
  if (msg.role === 'progress') {
    return (
      <div class="text-xs text-text-dim opacity-60 px-3 py-1">
        {msg.content.slice(0, 300)}
      </div>
    );
  }
  if (msg.role === 'error') {
    return (
      <div class="bg-error/10 border border-error/30 rounded-lg px-3 py-2 text-sm text-error">
        {msg.content}
      </div>
    );
  }

  const isUser = msg.role === 'user';
  return (
    <div class={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        class={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? 'bg-accent/15 text-text border border-accent/20'
            : 'bg-surface border border-border'
        }`}
        dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
      />
    </div>
  );
}
