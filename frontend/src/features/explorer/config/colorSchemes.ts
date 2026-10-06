import {
  interpolatePlasma,
  interpolateReds,
} from "d3-scale-chromatic";

export type ColorInterpolator = (value: number) => string;

const COLOR_INTERPOLATORS: Record<string, ColorInterpolator> = {
  Plasma: interpolatePlasma,
  Reds: interpolateReds,
};

/**
 * Return one of the color schemes used by the map configuration.
 *
 * Keeping this registry explicit lets the bundler omit the many unused D3
 * palettes that a namespace import would otherwise retain.
 */
export function getColorInterpolator(
  colorScheme: string,
): ColorInterpolator | null {
  return COLOR_INTERPOLATORS[colorScheme] ?? null;
}
