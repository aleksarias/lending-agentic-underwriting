/**
 * Screen 14 (lessons) — what the curator agent has learned, by definition of default. Lessons are agent claims.
 */
import { Link } from "react-router-dom";
import { useLessons } from "../api/hooks";
import { LessonsView, lessonsSentence } from "../components/Lessons/LessonsView";
import { useDefinitionRefs } from "../components/Agents/shared";
import { DefinitionBadge, Page, PageHeader, QueryView } from "../components/ui";

export default function Lessons() {
  const q = useLessons();
  const { active } = useDefinitionRefs();
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(d) => (
          <>
            <PageHeader
              eyebrow="Agents"
              title="Lessons"
              summary={lessonsSentence(d, active)}
              meta={
                <>
                  <Link to="/agents">Agents</Link>
                  <span>· definition of default</span>
                  <DefinitionBadge def={active} version={d.active_definition} />
                </>
              }
            />
            <LessonsView data={d} />
          </>
        )}
      </QueryView>
    </Page>
  );
}
