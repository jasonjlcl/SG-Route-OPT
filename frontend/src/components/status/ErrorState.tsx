import { AlertTriangle, ArrowRight } from "lucide-react";

import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

type ErrorStateProps = {
  title: string;
  cause: string;
  nextStep: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function ErrorState({ title, cause, nextStep, actionLabel = "Try again", onAction }: ErrorStateProps) {
  return (
    <Card className="border-danger/30 bg-danger/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-danger">
          <AlertTriangle className="h-5 w-5" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>
          <span className="font-semibold">What happened:</span> {cause}
        </p>
        <p>
          <span className="font-semibold">What to do next:</span> {nextStep}
        </p>
        {onAction && (
          <Button variant="danger" onClick={onAction}>
            {actionLabel}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
