/**
 * Building blocks for actions (run the gate, approve, promote, acknowledge).
 *
 * - ActionButton: disabled with a stated reason instead of hidden. The reason is a tooltip on the button and its
 *   wrapper (disabled buttons do not always show their own tooltip) and is exposed to screen readers.
 * - ActionDialog: the shared ConfirmDialog plus what it lacks for keyboard users: focus moves into the dialog, Tab stays
 *   inside it, Escape cancels, and focus returns to the button that opened it.
 */
import { useEffect, useRef, type ComponentProps, type ReactNode } from "react";
import { ConfirmDialog } from "../ui";

export function ActionButton(props: {
  children: ReactNode;
  onClick: () => void;
  /** When set, the button is disabled and this text says why. */
  disabledReason?: string | null;
  variant?: "primary" | "danger" | "default";
  small?: boolean;
}) {
  const { children, onClick, disabledReason, variant = "default", small } = props;
  const disabled = !!disabledReason;
  return (
    <span title={disabledReason ?? undefined} style={{ display: "inline-flex" }}>
      <button
        type="button"
        className={["btn", variant === "default" ? "" : variant, small ? "small" : ""].join(" ").trim()}
        disabled={disabled}
        title={disabledReason ?? undefined}
        aria-label={disabled && typeof children === "string" ? `${children} (unavailable: ${disabledReason})` : undefined}
        onClick={onClick}
      >
        {children}
      </button>
    </span>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function ActionDialog(props: ComponentProps<typeof ConfirmDialog>) {
  const rootRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef(props.onCancel);
  const busyRef = useRef(props.busy);
  cancelRef.current = props.onCancel;
  busyRef.current = props.busy;

  useEffect(() => {
    const root = rootRef.current;
    const opener = document.activeElement as HTMLElement | null;
    const dialog = root?.querySelector<HTMLElement>('[role="dialog"]');
    const first = dialog?.querySelector<HTMLElement>("textarea, button:not([disabled])");
    first?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        if (!busyRef.current) cancelRef.current();
        return;
      }
      if (e.key !== "Tab" || !dialog) return;
      const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === firstItem || !dialog.contains(active))) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && (active === lastItem || !dialog.contains(active))) {
        e.preventDefault();
        firstItem.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  // display: contents keeps the wrapper out of the page grid (the dialog itself is position: fixed)
  return (
    <div ref={rootRef} style={{ display: "contents" }}>
      <ConfirmDialog {...props} />
    </div>
  );
}
