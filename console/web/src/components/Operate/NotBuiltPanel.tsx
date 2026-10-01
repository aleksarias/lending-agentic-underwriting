/**
 * The designed state for a backend that is not built yet (decision API, live loan feed, staged rollouts).
 * It says plainly what is missing, what the screen will show once it exists, and what it needs. It never shows numbers.
 */
import type { ReactNode } from "react";
import { Pill } from "../ui";
import "./operate.css";

export interface WillShow {
  title: string;
  detail: string;
}

export function NotBuiltPanel(props: {
  title: string;
  reason: string;
  requires: string[];
  willShow: WillShow[];
  footer?: ReactNode;
}) {
  return (
    <section className="card operate-notbuilt" aria-label={props.title}>
      <div className="row">
        <Pill tone="neutral">Not available yet</Pill>
        <strong>{props.title}</strong>
      </div>
      <p className="small operate-lead">{props.reason}</p>
      <div className="operate-cols">
        <div>
          <h3 className="operate-h">What this will show</h3>
          <ul className="operate-list">
            {props.willShow.map((w) => (
              <li key={w.title}>
                <strong>{w.title}</strong>
                <span className="detail">{w.detail}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="operate-h">What it needs</h3>
          {props.requires.length ? (
            <ul className="operate-list">
              {props.requires.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : (
            <p className="small muted" style={{ margin: 0 }}>
              The API lists no separate requirements.
            </p>
          )}
        </div>
      </div>
      {props.footer}
    </section>
  );
}
