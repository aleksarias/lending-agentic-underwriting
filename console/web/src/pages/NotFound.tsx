import { Link } from "react-router-dom";
import { EmptyState, Page, PageHeader } from "../components/ui";

export default function NotFound() {
  return (
    <Page>
      <PageHeader title="Page not found" />
      <EmptyState title="There is nothing at this address" action={<Link to="/">Go to the overview</Link>} />
    </Page>
  );
}
