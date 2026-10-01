/** The API answers 404 for an id it does not know and 400 for one that is not a plain identifier. */
export function isMissing(error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status;
  return status === 404 || status === 400;
}
