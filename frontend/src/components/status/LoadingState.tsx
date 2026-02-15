import { Skeleton } from "../ui/skeleton";

type LoadingStateProps = {
  title?: string;
};

export function LoadingState({ title = "Loading" }: LoadingStateProps) {
  return (
    <div className="space-y-4">
      <p className="text-sm font-medium text-muted-foreground">{title}...</p>
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-56 w-full rounded-xl" />
    </div>
  );
}
