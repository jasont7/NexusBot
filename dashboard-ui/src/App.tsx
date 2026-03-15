import { useState } from 'preact/hooks';
import { Shell, TabId } from './components/Shell';
import { useWebSocket } from './hooks/useWebSocket';
import { Home } from './pages/Home';
import { Chat } from './pages/Chat';
import { Agents } from './pages/Agents';
import { Twitter } from './pages/Twitter';
import { Email } from './pages/Email';
import { Research } from './pages/Research';
import { GitHub } from './pages/GitHub';
import { Brain } from './pages/Brain';
import { System } from './pages/System';
import { Architecture } from './pages/Architecture';

const PAGES: Record<TabId, () => preact.JSX.Element> = {
  home: Home,
  chat: Chat,
  agents: Agents,
  twitter: Twitter,
  email: Email,
  research: Research,
  github: GitHub,
  brain: Brain,
  architecture: Architecture,
  system: System,
};

export function App() {
  const [tab, setTab] = useState<TabId>('home');
  const connected = useWebSocket();

  const Page = PAGES[tab] || Home;

  return (
    <Shell activeTab={tab} onTabChange={setTab} connected={connected}>
      <Page />
    </Shell>
  );
}
