import { useEffect, useRef, useState, type ReactNode } from "react";

export interface DropdownItem {
  id: string;
  label: string;
}

interface DropdownProps {
  trigger: ReactNode;
  items: DropdownItem[];
  activeId?: string;
  onSelect: (id: string) => void;
  className?: string;
  title?: string;
  disabled?: boolean;
  disabledReason?: string;
}

// Self-contained, positioned dropdown. One instance per picker; no global
// state. Add new pickers (e.g. modes) by dropping in another <Dropdown/>.
export function Dropdown({
  trigger,
  items,
  activeId,
  onSelect,
  className = "ctrl-btn",
  title,
  disabled = false,
  disabledReason,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const toggle = () => {
    if (disabled) return;
    if (open) {
      setOpen(false);
      return;
    }
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect) {
      const height = Math.min(240, items.length * 32 + 8);
      const top = rect.bottom + height > window.innerHeight ? rect.top - height - 4 : rect.bottom + 4;
      const left = Math.min(rect.left, window.innerWidth - 200);
      setPos({ top, left });
    }
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest(".dropdown") && !t.closest(".ctrl-btn") && !t.closest(".model-picker")) setOpen(false);
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        className={`${className}${disabled ? " is-disabled" : ""}`}
        onClick={toggle}
        title={disabled ? disabledReason : title}
        disabled={disabled}
        type="button"
      >
        {trigger}
      </button>
      {open && pos && (
        <div className="dropdown active" style={{ top: pos.top, left: pos.left }}>
          <div className="dropdown-content">
            {items.map((it) => (
              <div
                key={it.id}
                className={`dropdown-item ${it.id === activeId ? "active" : ""}`}
                onClick={() => {
                  onSelect(it.id);
                  setOpen(false);
                }}
              >
                {it.label}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
