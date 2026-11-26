import {
  Activity,
  ArrowDownRight,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Bell,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  Code2,
  Command,
  Copy,
  Cpu,
  Database,
  Download,
  FileCheck2,
  FileText,
  Gauge,
  History,
  Home,
  KeyRound,
  Layers3,
  LockKeyhole,
  LogOut,
  Menu,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Plus,
  Search,
  Send,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  Trash2,
  UserRound,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";

const icons = {
  activity: Activity,
  "arrow-down-right": ArrowDownRight,
  "arrow-left": ArrowLeft,
  "arrow-right": ArrowRight,
  "arrow-up-right": ArrowUpRight,
  bell: Bell,
  book: BookOpen,
  check: Check,
  "check-circle": CheckCircle2,
  "chevron-down": ChevronDown,
  "chevron-left": ChevronLeft,
  "chevron-right": ChevronRight,
  code: Code2,
  help: CircleHelp,
  clock: Clock3,
  command: Command,
  copy: Copy,
  cpu: Cpu,
  database: Database,
  download: Download,
  "file-check": FileCheck2,
  "file-text": FileText,
  gauge: Gauge,
  history: History,
  home: Home,
  key: KeyRound,
  layers: Layers3,
  lock: LockKeyhole,
  logout: LogOut,
  menu: Menu,
  message: MessageSquare,
  more: MoreHorizontal,
  "panel-close": PanelLeftClose,
  "panel-open": PanelLeftOpen,
  paperclip: Paperclip,
  plus: Plus,
  search: Search,
  send: Send,
  server: Server,
  settings: Settings2,
  shield: ShieldCheck,
  sliders: SlidersHorizontal,
  sparkles: Sparkles,
  terminal: Terminal,
  trash: Trash2,
  user: UserRound,
  close: X,
  zap: Zap,
} satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof icons;

export function Icon({
  name,
  size = 18,
  strokeWidth = 1.8,
  className,
}: {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  const Component = icons[name];
  return (
    <Component
      aria-hidden="true"
      className={className}
      size={size}
      strokeWidth={strokeWidth}
    />
  );
}
