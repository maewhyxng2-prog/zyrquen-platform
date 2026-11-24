import { WorkspaceClient } from "@/components/WorkspaceClient";

export const dynamic = "force-dynamic";

export default function WorkspacePage() {
  const allowUnauthenticatedEntry = process.env.NODE_ENV !== "production";
  return (
    <WorkspaceClient allowUnauthenticatedEntry={allowUnauthenticatedEntry} />
  );
}
