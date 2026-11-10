import { errorText } from "./api/client";
import type { ReactNode } from "react";

export function ErrorNotice({ error }: { error: unknown }) {
  return error ? (
    <div className="notice error" role="alert">
      {errorText(error)}
    </div>
  ) : null;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="eyebrow">RESEARCH NOTE</span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      正在读取研究资料…
    </div>
  );
}
