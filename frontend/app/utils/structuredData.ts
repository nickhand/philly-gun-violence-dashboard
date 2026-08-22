export type StructuredDataNode = Record<string, unknown>;

export const NICK_HAND_GITHUB_URL = "https://github.com/nickhand";
export const OPEN_DATA_PHILLY_URL = "https://opendataphilly.org/";
export const PPD_HOMICIDE_SOURCE_URL =
  "https://www.phillypolice.com/crime-data/crime-statistics/";
export const PPD_ORGANIZATION_URL =
  "https://www.phila.gov/departments/philadelphia-police-department/";
export const PPD_SHOOTING_SOURCE_URL =
  "https://opendataphilly.org/datasets/shooting-victims/";
export const UJS_CASE_SEARCH_URL =
  "https://ujsportal.pacourts.us/CaseSearch";

export interface DashboardEntityIds {
  aboutPage: string;
  courtSourcePage: string;
  dataPage: string;
  dashboardDataset: string;
  homicideSourceDataset: string;
  methodologyPage: string;
  openDataCatalog: string;
  person: string;
  policeDepartment: string;
  profileUrl: string;
  shootingSourceDataset: string;
  siteUrl: string;
  statsDataset: string;
  statsPage: string;
  website: string;
}

export function getDashboardEntityIds(value: string): DashboardEntityIds {
  const siteUrl = value.replace(/\/+$/, "");
  const profileUrl = new URL("/", siteUrl).href;

  return {
    aboutPage: `${siteUrl}/about#webpage`,
    courtSourcePage: `${UJS_CASE_SEARCH_URL}#webpage`,
    dataPage: `${siteUrl}/data#webpage`,
    dashboardDataset: `${siteUrl}/data#dataset`,
    homicideSourceDataset: `${PPD_HOMICIDE_SOURCE_URL}#dataset`,
    methodologyPage: `${siteUrl}/methodology#webpage`,
    openDataCatalog: `${OPEN_DATA_PHILLY_URL}#catalog`,
    person: `${profileUrl}#person`,
    policeDepartment: `${PPD_ORGANIZATION_URL}#organization`,
    profileUrl,
    shootingSourceDataset: `${PPD_SHOOTING_SOURCE_URL}#dataset`,
    siteUrl,
    statsDataset: `${siteUrl}/stats#dataset`,
    statsPage: `${siteUrl}/stats#webpage`,
    website: `${siteUrl}#website`,
  };
}

export function createCourtSourceEntity(
  ids: DashboardEntityIds,
): StructuredDataNode {
  return {
    "@type": "WebPage",
    "@id": ids.courtSourcePage,
    name: "Pennsylvania Unified Judicial System public case search",
    url: UJS_CASE_SEARCH_URL,
  };
}

export function createDashboardIdentityEntities(
  ids: DashboardEntityIds,
): StructuredDataNode[] {
  return [
    {
      "@type": "Person",
      "@id": ids.person,
      name: "Nick Hand",
      url: ids.profileUrl,
      sameAs: [NICK_HAND_GITHUB_URL],
    },
    {
      "@type": "WebSite",
      "@id": ids.website,
      name: "Philadelphia Gun Violence Dashboard",
      url: ids.siteUrl,
      description:
        "An independently maintained dashboard for exploring and downloading public Philadelphia shooting-victim records.",
      inLanguage: "en-US",
      isAccessibleForFree: true,
      creator: { "@id": ids.person },
      maintainer: { "@id": ids.person },
      publisher: { "@id": ids.person },
    },
  ];
}

export function createDashboardPersonEntity(
  ids: DashboardEntityIds,
): StructuredDataNode {
  return {
    "@type": "Person",
    "@id": ids.person,
    name: "Nick Hand",
    url: ids.profileUrl,
    sameAs: [NICK_HAND_GITHUB_URL],
  };
}

export function createDashboardPageProvenance(
  ids: DashboardEntityIds,
): StructuredDataNode {
  return {
    isPartOf: { "@id": ids.website },
    author: { "@id": ids.person },
    publisher: { "@id": ids.person },
    inLanguage: "en-US",
  };
}

export function createDashboardDatasetProvenance(
  ids: DashboardEntityIds,
): StructuredDataNode {
  return {
    creator: createDashboardPersonEntity(ids),
    maintainer: { "@id": ids.person },
    publisher: createDashboardPersonEntity(ids),
    license: {
      "@type": "CreativeWork",
      name: "Licensing and terms for dashboard data",
      url: `${ids.siteUrl}/data#terms-methods`,
    },
  };
}
