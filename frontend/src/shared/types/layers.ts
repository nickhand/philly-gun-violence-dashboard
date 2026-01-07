export type TitleFunction = (data: any) => string;

interface BaseLayerConfig {
  name: string;
  source: string;
  aggregated: true | false;
  paint?: object;
  overlay?: true | false;
  showOnStart?: true | false;
  static?: true | false;
  column?: string;
  geoid?: string;
  tooltip?: {
    formatter: (data: any) => string;
    on: "mousemove" | "mouseenter";
  };
  legend?: {
    colorScheme: string;
    scaleName: string;
    colorRange: [number, number];
  };
  beforeId?: string;
}

export interface AggregatedLayerConfig extends BaseLayerConfig {
  aggregated: true;
  column: string;
  geoid: string;
  type: "fill";
}

export interface MapLayerConfig extends BaseLayerConfig {
  type: "line" | "circle" | "heatmap";
}

export type LayerConfig = AggregatedLayerConfig | MapLayerConfig;
