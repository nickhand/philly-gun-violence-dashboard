export interface PageMeta {
  limit: number;
  offset: number;
  count: number;
  total: number;
  next_offset: number | null;
}
