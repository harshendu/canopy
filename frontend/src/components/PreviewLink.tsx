import type { MouseEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import { usePreview } from "../lib/preview";
import { targetPath, type PreviewTarget } from "../lib/previewTarget";

/**
 * A link to an entity that opens the right-side preview drawer on a plain click instead of
 * navigating immediately — the app-wide "peek before you leave the page" affordance. It still
 * renders a real `<a href>`, so keyboard focus, middle-click, and ⌘/Ctrl-click (open in new
 * tab) all behave like a normal link; only an unmodified primary click is intercepted.
 */
export function PreviewLink({
  target,
  className,
  children,
  title,
  "aria-label": ariaLabel,
}: {
  target: PreviewTarget;
  className?: string;
  children: ReactNode;
  title?: string;
  "aria-label"?: string;
}) {
  const { openPreview } = usePreview();

  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (
      e.defaultPrevented ||
      e.button !== 0 ||
      e.metaKey ||
      e.ctrlKey ||
      e.shiftKey ||
      e.altKey
    ) {
      return; // let the browser handle new-tab / new-window / modified clicks
    }
    e.preventDefault();
    openPreview(target);
  };

  return (
    <Link to={targetPath(target)} className={className} title={title} aria-label={ariaLabel} onClick={onClick}>
      {children}
    </Link>
  );
}
