/** Plain-language messages for the ways a question can fail. Status codes are the ask endpoint's (routers/search.py). */
import { ApiError } from "../../api/client";

export interface AskProblem {
  title: string;
  body: string;
  /** the server's own words, shown small, when they add detail */
  detail?: string;
  /** a screen that explains more */
  link?: { to: string; label: string };
}

export function describeAskError(error: unknown): AskProblem {
  if (error instanceof ApiError) {
    if (error.status === 503) {
      return {
        title: "Questions cannot be answered on this console",
        body: "The Anthropic API key is not configured here, so the agent that answers questions cannot run. Everything else in the console works without it. An administrator can add the key to the console's environment.",
        detail: error.detail,
      };
    }
    if (error.status === 429) {
      return {
        title: "This month's agent budget is used up",
        body: "The console stops asking the agent once spend reaches the monthly hard stop, so that cost stays predictable. Questions work again next month, or sooner if an administrator raises the limit.",
        detail: error.detail,
        link: { to: "/cost", label: "See spend on the Cost screen" },
      };
    }
    if (error.status === 400) {
      const tooLong = /2,?000/.test(error.detail);
      return {
        title: tooLong ? "The question is too long" : "Type a question first",
        body: tooLong ? "Keep the question under 2,000 characters." : "A question needs at least 3 characters.",
      };
    }
    return { title: "The question could not be answered", body: "The console reported an error while the agent was working.", detail: error.detail || `Error ${error.status}` };
  }
  const message = error instanceof Error ? error.message : String(error);
  return {
    title: "The question could not be sent",
    body: "The console API did not respond. Check that the console is running, then try again.",
    detail: message,
  };
}
