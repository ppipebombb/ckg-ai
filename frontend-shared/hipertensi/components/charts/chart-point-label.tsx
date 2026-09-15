"use client";

import type { LabelProps } from "recharts";
import { fmtCount } from "./theme";

/**
 * Vertical space the label stack occupies above a point. Charts that use
 * ChartPointLabel must keep at least this much `margin.top`, or the topmost
 * label is clipped by the SVG bounds — recharts does not constrain label
 * content to the plot area.
 */
export const POINT_LABEL_HEADROOM = 36;

export type ChartPointLabelProps = LabelProps & {
  /**
   * Bold first line per point, indexed by point index. Needed when the series
   * plots something other than the count — the percentage-scaled charts plot a
   * share, so the count they want in bold is not the `value` recharts passes
   * in. Omit to label the plotted value itself.
   */
  counts?: readonly number[];
  /**
   * Muted second line per point, indexed by point index. Recharts strips
   * `payload` before label content renders (only x/y/value/index survive), so a
   * caption that isn't the plotted value has to be looked up by index.
   * Omit for a count-only label.
   */
  captions?: readonly string[];
  /** Drop the label where the count is 0, so flat stretches stay readable. */
  hideZero?: boolean;
  /**
   * Draw the stack below the point instead of above. On a chart with two
   * series that converge, label the upper series above and the lower series
   * below: the labels then sit outside the band between the lines and can
   * never collide, however close the lines get.
   */
  below?: boolean;
};

/**
 * Two-line label above a Line/Area point: the count in bold, with an optional
 * muted caption (usually a percentage) beneath it.
 *
 * Pass this as an ELEMENT — `label={<ChartPointLabel captions={c} />}` — never
 * as an inline arrow. Recharts renders label content via `createElement`, so a
 * function rebuilt each render is a new component type and remounts every
 * label; an element keeps the type stable and only updates props.
 */
export function ChartPointLabel({
  x,
  y,
  value,
  index,
  counts,
  captions,
  hideZero,
  below,
}: ChartPointLabelProps) {
  const cx = Number(x);
  const cy = Number(y);
  const count = Number(
    counts && index !== undefined ? counts[index] : value,
  );
  if (!Number.isFinite(count) || !Number.isFinite(cx) || !Number.isFinite(cy)) {
    return null;
  }
  if (hideZero && count === 0) return null;

  const caption = index === undefined ? undefined : captions?.[index];
  // Count always sits nearest the point, caption outside it.
  const countY = below ? cy + 18 : cy - (caption ? 20 : 8);
  const captionY = below ? cy + 29 : cy - 8;
  return (
    <g>
      <text
        x={cx}
        y={countY}
        fill="var(--foreground)"
        fontSize={11}
        fontWeight={600}
        textAnchor="middle"
      >
        {fmtCount(count)}
      </text>
      {caption ? (
        <text
          x={cx}
          y={captionY}
          fill="var(--muted-foreground)"
          fontSize={10}
          textAnchor="middle"
        >
          {caption}
        </text>
      ) : null}
    </g>
  );
}
