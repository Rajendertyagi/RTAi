import { useMemo } from "react";

type DiffLine = { type: "same" | "add" | "remove"; text: string };

/**
 * Line-based diff (LCS) with a size cap. Large inputs fall back to showing
 * all old lines as removed and all new lines as added rather than blowing up.
 */
function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = oldText.split("\n");
  const b = newText.split("\n");
  const n = a.length;
  const m = b.length;

  if (n * m > 250_000) {
    return [
      ...a.map((text) => ({ type: "remove" as const, text })),
      ...b.map((text) => ({ type: "add" as const, text })),
    ];
  }

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result.push({ type: "same", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: "remove", text: a[i] });
      i++;
    } else {
      result.push({ type: "add", text: b[j] });
      j++;
    }
  }
  while (i < n) {
    result.push({ type: "remove", text: a[i] });
    i++;
  }
  while (j < m) {
    result.push({ type: "add", text: b[j] });
    j++;
  }
  return result;
}

export function DiffPreview({
  oldText,
  newText,
  path,
}: {
  oldText?: string;
  newText: string;
  path: string;
}) {
  const lines = useMemo(() => diffLines(oldText ?? "", newText), [oldText, newText]);

  return (
    <div className="diff-preview">
      <div className="diff-path" title={path}>
        {path}
      </div>
      <pre className="diff-body">
        {lines.map((line, index) => (
          <div key={index} className={`diff-line ${line.type}`}>
            <span className="diff-marker">{line.type === "add" ? "+" : line.type === "remove" ? "-" : " "}</span>
            <span className="diff-text">{line.text || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}