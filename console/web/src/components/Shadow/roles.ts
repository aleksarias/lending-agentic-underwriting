/** What each shadow-scoring role means, as the shadow job defines it (lau.promotion.shadow). */
export const ROLE_LABEL: Record<string, string> = {
  serving: "Serving model",
  challenger: "Challenger",
  baseline: "Baseline",
};

export const ROLE_HELP: Record<string, string> = {
  serving: "The model that holds the serving alias in the production registry.",
  challenger: "The newest challenger for the active definition of default.",
  baseline: "The definition's baseline, scored only when there is neither a serving model nor a challenger.",
};

export const roleLabel = (role: string): string => ROLE_LABEL[role] ?? role.charAt(0).toUpperCase() + role.slice(1);
