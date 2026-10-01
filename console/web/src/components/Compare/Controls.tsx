/** The two instants to compare (UTC, kept in the URL) and one-click presets built from the definition changes. */
import { formatInstant, parseInstant, type Preset } from "./instants";

export function Controls(props: {
  from: number;
  to: number;
  fromInUrl: boolean;
  toInUrl: boolean;
  presets: Preset[];
  reversed: boolean;
  onFrom: (value: string) => void;
  onTo: (value: string) => void;
  onPreset: (p: Preset) => void;
  onReset: () => void;
}) {
  const { from, to } = props;
  // A half-typed date reads as an empty value; wait until it is a whole date and time.
  const commit = (apply: (v: string) => void) => (e: { target: { value: string } }) => {
    if (parseInstant(e.target.value) != null) apply(e.target.value);
  };
  return (
    <div className="compare-controls">
      <div className="compare-dates">
        <label className="field">
          From (UTC)
          <input type="datetime-local" step={1} value={formatInstant(from)} onChange={commit(props.onFrom)} />
        </label>
        <label className="field">
          To (UTC)
          <input type="datetime-local" step={1} value={formatInstant(to)} onChange={commit(props.onTo)} />
        </label>
        {(props.fromInUrl || props.toInUrl) && (
          <button type="button" className="btn small compare-reset" onClick={props.onReset}>
            Reset dates
          </button>
        )}
      </div>
      <div className="xs muted">
        Both dates are UTC.
        {!props.fromInUrl && " From is the first definition activation until you pick a date."}
        {!props.toInUrl && " To is the moment this page opened until you pick a date."}
      </div>
      {props.reversed && (
        <div className="small" role="status">
          From is later than To, so the two dates are compared in the other order.
        </div>
      )}
      {props.presets.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <strong className="small" id="compare-presets-label">
            Presets
          </strong>
          <div className="compare-presets" role="group" aria-labelledby="compare-presets-label">
            {props.presets.map((p) => {
              const on = p.from === from && p.to === to;
              return (
                <button key={p.key} type="button" className="compare-preset" aria-pressed={on} onClick={() => props.onPreset(p)}>
                  <span className="compare-preset-label">
                    {on && <span aria-hidden>✓ </span>}
                    {p.label}
                  </span>
                  <span className="xs muted">{p.detail}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
