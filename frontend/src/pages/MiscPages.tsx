import { Link } from "react-router";

import { EmptyState } from "@/components/ui/feedback";
import { Panel } from "@/components/ui/surface";

export function NotFoundPage() {
  return (
    <Panel>
      <EmptyState title="This page does not exist." action={<Link to="/" className="text-sm text-accent hover:underline">Go to the dashboard</Link>}>
        Check the address, or use Ctrl+K to find a section.
      </EmptyState>
    </Panel>
  );
}

export function NoAccessPage({ permission }: { permission: string }) {
  return (
    <Panel>
      <EmptyState title="You do not have access to this page.">
        It requires the <code className="text-fg">{permission}</code> permission. Ask an
        administrator if you need it.
      </EmptyState>
    </Panel>
  );
}
