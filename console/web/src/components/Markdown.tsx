/** Renders agent-written markdown safely (marked -> DOMPurify). Agent reports are untrusted text. */
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

marked.setOptions({ gfm: true, breaks: false });

export function Markdown({ source }: { source: string }) {
  const html = useMemo(() => {
    const raw = marked.parse(source ?? "", { async: false }) as string;
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true }, FORBID_TAGS: ["style", "iframe", "form", "input"], FORBID_ATTR: ["style", "onerror", "onclick"] });
  }, [source]);
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}
