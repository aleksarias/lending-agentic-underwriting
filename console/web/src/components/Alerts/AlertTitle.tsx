/** The alert headline. A feature alert links to that variable's catalog page, where its drift and risk ratings live. */
import { Link } from "react-router-dom";
import type { AlertItem } from "../../api/types";
import { links } from "../ui";
import { alertTitle, subjectLabel } from "./logic";

export function AlertTitle({ a }: { a: AlertItem }) {
  if (a.kind === "psi" && a.subject !== "score") {
    return (
      <>
        Distribution of <Link to={links.variable(a.subject)}>{subjectLabel(a.subject)}</Link> shifted
      </>
    );
  }
  return <>{alertTitle(a)}</>;
}
