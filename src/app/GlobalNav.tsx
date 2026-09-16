import {
  BriefcaseBusiness,
  Clock3,
  Images,
  Settings,
  Trash2,
} from "lucide-react";

export type GlobalPanel = "projects" | "assets" | "jobs" | "trash" | "settings";

const items = [
  { id: "projects", label: "项目", icon: BriefcaseBusiness },
  { id: "assets", label: "资产中心", icon: Images },
  { id: "jobs", label: "任务", icon: Clock3 },
  { id: "trash", label: "回收站", icon: Trash2 },
  { id: "settings", label: "设置", icon: Settings },
] as const;

export function GlobalNav({
  active,
  taskCount,
  onChange,
  isAdmin = false,
}: {
  active: string | null;
  taskCount: number;
  onChange: (panel: GlobalPanel) => void;
  isAdmin?: boolean;
}) {
  return (
    <nav className="rail global-nav" aria-label="全局导航">
      {items.filter(({id})=>id!=="settings"||isAdmin).map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          className={active === id ? "active" : ""}
          title={label}
          aria-label={id === "jobs" ? `${label} ${taskCount}` : label}
          onClick={() => onChange(id)}
        >
          <Icon />
          <span>{label}</span>
          {id === "jobs" && taskCount > 0 && <b>{taskCount}</b>}
        </button>
      ))}
    </nav>
  );
}

