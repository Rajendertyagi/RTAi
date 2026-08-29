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

// Model lists run into the hundreds, so offer a filter box once a list is long
// enough to need one.
const SEARCH_THRESHOLD = 8;
// Cap rendered rows so a very large list stays responsive.
const MAX_RENDERED = 100;

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
  const [filter, setFilter] = useState("");
  const btnRef = useRef<HTMLButtonElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);

  const showSearch = items.length > SEARCH_THRESHOLD;
  const needle = filter.trim().toLowerCase();
  const filtered = needle
    ? items.filter((it) => it.label.toLowerCase().includes(needle))
    : items;
  const visible = filtered.slice(0, MAX_RENDERED);

  const close = () => {
    setOpen(false);
    setFilter("");
  };

  const toggle = () => {
    if (disabled) return;
    if (open) {
      close();
      return;
    }
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect) {
      const height = Math.min(240, filtered.length * 32 + (showSearch ? 44 : 8));
      // Always open upward for visual consistency across pickers; fall back to
      // downward only when the menu would overflow the top of the window.
      const top = rect.top - height - 4 < 0 ? rect.bottom + 4 : rect.top - height - 4;
      const left = Math.min(rect.left, window.innerWidth - 200);
      setPos({ top, left });
    }
    setFilter("");
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    if (showSearch) filterRef.current?.focus();
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest(".dropdown") && !t.closest(".ctrl-btn") && !t.closest(".model-picker")) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
      }
    };
    document.addEventListener("click", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, showSearch]);

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
          {showSearch && (
            <input
              ref={filterRef}
              className="dropdown-search"
              type="text"
              value={filter}
              placeholder="Filter..."
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.stopPropagation();
                  close();
                }
              }}
            />
          )}
          <div className="dropdown-content">
            {visible.length === 0 ? (
              <div className="dropdown-empty">No matches</div>
            ) : (
              visible.map((it) => (
                <div
                  key={it.id}
                  className={`dropdown-item ${it.id === activeId ? "active" : ""}`}
                  onClick={() => {
                    onSelect(it.id);
                    close();
                  }}
                >
                  {it.label}
                </div>
              ))
            )}
            {filtered.length > visible.length && (
              <div className="dropdown-empty">
                {filtered.length - visible.length} more — keep typing to narrow
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
