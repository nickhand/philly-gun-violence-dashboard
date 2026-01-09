// Type declarations for d3 modules
declare module "d3-array" {
  export function rollup<T, U>(
    iterable: Iterable<T>,
    reduce: (values: T[]) => U,
    ...keys: ((value: T) => unknown)[]
  ): Map<unknown, U>;

  export function extent<T>(
    iterable: Iterable<T>,
    accessor?: (datum: T) => number | undefined | null
  ): [number, number] | [undefined, undefined];
}

declare module "d3-scale" {
  export interface ScaleLinear<Range, Output> {
    (value: number): Output;
    domain(): number[];
    domain(domain: Iterable<number>): this;
    range(): Range[];
    range(range: Iterable<Range>): this;
    clamp(): boolean;
    clamp(clamp: boolean): this;
    ticks(count?: number): number[];
  }

  export interface ScaleLogarithmic<Range, Output>
    extends ScaleLinear<Range, Output> {}

  export interface ScaleSequential<Output> {
    (value: number): Output;
    domain(): [number, number];
    domain(domain: [number, number]): this;
    interpolator(): (t: number) => Output;
    interpolator(interpolator: (t: number) => Output): this;
    clamp(): boolean;
    clamp(clamp: boolean): this;
  }

  export function scaleLinear<Range = number, Output = Range>(): ScaleLinear<
    Range,
    Output
  >;
  export function scaleLog<Range = number, Output = Range>(): ScaleLogarithmic<
    Range,
    Output
  >;
  export function scaleSequential<Output = number>(
    interpolator?: (t: number) => Output
  ): ScaleSequential<Output>;
  export function scaleSequentialLog<Output = number>(
    interpolator?: (t: number) => Output
  ): ScaleSequential<Output>;
}

declare module "d3-scale-chromatic" {
  export function interpolatePlasma(t: number): string;
  export function interpolateViridis(t: number): string;
  export function interpolateInferno(t: number): string;
  export function interpolateMagma(t: number): string;
  export function interpolateCividis(t: number): string;
  export function interpolateWarm(t: number): string;
  export function interpolateCool(t: number): string;
  export function interpolateRainbow(t: number): string;
  export function interpolateYlOrRd(t: number): string;
  export function interpolateYlGnBu(t: number): string;
  export function interpolateRdYlBu(t: number): string;
  export function interpolateRdYlGn(t: number): string;
  export function interpolateSpectral(t: number): string;
  export function interpolateBlues(t: number): string;
  export function interpolateGreens(t: number): string;
  export function interpolateGreys(t: number): string;
  export function interpolateOranges(t: number): string;
  export function interpolatePurples(t: number): string;
  export function interpolateReds(t: number): string;
  export function interpolateTurbo(t: number): string;
  export function interpolateBuGn(t: number): string;
  export function interpolateBuPu(t: number): string;
  export function interpolateGnBu(t: number): string;
  export function interpolateOrRd(t: number): string;
  export function interpolatePuBu(t: number): string;
  export function interpolatePuBuGn(t: number): string;
  export function interpolatePuRd(t: number): string;
  export function interpolateRdPu(t: number): string;
  export function interpolateYlGn(t: number): string;
}

declare module "d3-axis" {
  import { Selection } from "d3-selection";

  export interface Axis<Domain> {
    (context: Selection<SVGGElement, unknown, null, undefined>): void;
    scale<NewDomain>(): Axis<NewDomain>;
    scale(scale: unknown): this;
    ticks(...args: unknown[]): this;
    tickArguments(): unknown[];
    tickArguments(args: unknown[]): this;
    tickValues(): Domain[] | null;
    tickValues(values: Iterable<Domain> | null): this;
    tickFormat(): ((domainValue: Domain, index: number) => string) | null;
    tickFormat(
      format: ((domainValue: Domain, index: number) => string) | null
    ): this;
    tickSize(): number;
    tickSize(size: number): this;
    tickSizeInner(): number;
    tickSizeInner(size: number): this;
    tickSizeOuter(): number;
    tickSizeOuter(size: number): this;
    tickPadding(): number;
    tickPadding(padding: number): this;
    offset(): number;
    offset(offset: number): this;
  }

  export function axisBottom<Domain>(scale: unknown): Axis<Domain>;
  export function axisTop<Domain>(scale: unknown): Axis<Domain>;
  export function axisLeft<Domain>(scale: unknown): Axis<Domain>;
  export function axisRight<Domain>(scale: unknown): Axis<Domain>;
}

declare module "d3-selection" {
  export interface Selection<
    GElement extends Element,
    Datum,
    PElement extends Element | null,
    PDatum
  > {
    select<DescElement extends Element>(
      selector: string
    ): Selection<DescElement, Datum, PElement, PDatum>;
    selectAll<DescElement extends Element, NewDatum>(
      selector: string
    ): Selection<DescElement, NewDatum, GElement, Datum>;
    attr(name: string): string;
    attr(name: string, value: null): this;
    attr(name: string, value: string | number | boolean): this;
    attr(
      name: string,
      value: (
        datum: Datum,
        index: number,
        groups: GElement[]
      ) => string | number | boolean | null
    ): this;
    append<K extends keyof ElementTagNameMap>(
      type: K
    ): Selection<ElementTagNameMap[K], Datum, PElement, PDatum>;
    append<NewGElement extends Element>(
      type: string
    ): Selection<NewGElement, Datum, PElement, PDatum>;
    text(): string;
    text(value: null): this;
    text(value: string | number | boolean): this;
    text(
      value: (
        datum: Datum,
        index: number,
        groups: GElement[]
      ) => string | number | boolean | null
    ): this;
    call<Args extends unknown[]>(
      func: (selection: this, ...args: Args) => void,
      ...args: Args
    ): this;
    data<NewDatum>(): NewDatum[];
    data<NewDatum>(
      data: NewDatum[],
      key?: (
        datum: NewDatum | Datum,
        index: number,
        groups: GElement[] | PElement[]
      ) => string
    ): Selection<GElement, NewDatum, PElement, PDatum>;
    enter(): Selection<EnterElement, Datum, PElement, PDatum>;
    exit<OldDatum>(): Selection<GElement, OldDatum, PElement, PDatum>;
    merge(other: Selection<GElement, Datum, PElement, PDatum>): this;
    join<K extends keyof ElementTagNameMap>(
      enter: K
    ): Selection<GElement | ElementTagNameMap[K], Datum, PElement, PDatum>;
    remove(): this;
    style(name: string): string;
    style(name: string, value: null): this;
    style(
      name: string,
      value: string | number | boolean,
      priority?: null | "important"
    ): this;
    node(): GElement | null;
    nodes(): GElement[];
    empty(): boolean;
    each(func: (datum: Datum, index: number, groups: GElement[]) => void): this;
  }

  export interface EnterElement {
    ownerDocument: Document;
    namespaceURI: string;
  }

  export function select<GElement extends Element>(
    selector: string
  ): Selection<GElement, unknown, HTMLElement, unknown>;
  export function select<GElement extends Element>(
    node: GElement
  ): Selection<GElement, unknown, null, undefined>;
}
