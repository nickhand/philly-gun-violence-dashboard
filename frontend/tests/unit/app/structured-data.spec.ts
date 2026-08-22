import { describe, expect, it } from "vitest";

import {
  createCourtSourceEntity,
  createDashboardDatasetProvenance,
  createDashboardIdentityEntities,
  createDashboardPageProvenance,
  getDashboardEntityIds,
} from "../../../app/utils/structuredData";

const canonicalUrl =
  "https://www.nickhand.dev/philly-gun-violence-map";
const ids = getDashboardEntityIds(`${canonicalUrl}/`);

describe("dashboard structured-data identity", () => {
  it("builds stable identifiers from the canonical public URL", () => {
    expect(ids).toMatchObject({
      person: "https://www.nickhand.dev/#person",
      website: `${canonicalUrl}#website`,
      dashboardDataset: `${canonicalUrl}/data#dataset`,
      statsDataset: `${canonicalUrl}/stats#dataset`,
      shootingSourceDataset:
        "https://opendataphilly.org/datasets/shooting-victims/#dataset",
    });
  });

  it("connects pages and dashboard datasets to the same maintainer", () => {
    const [person, website] = createDashboardIdentityEntities(ids);

    expect(person).toMatchObject({
      "@type": "Person",
      "@id": ids.person,
      name: "Nick Hand",
    });
    expect(website).toMatchObject({
      "@type": "WebSite",
      "@id": ids.website,
      creator: { "@id": ids.person },
      maintainer: { "@id": ids.person },
      publisher: { "@id": ids.person },
    });
    expect(createDashboardPageProvenance(ids)).toMatchObject({
      isPartOf: { "@id": ids.website },
      author: { "@id": ids.person },
    });
    expect(createDashboardDatasetProvenance(ids)).toMatchObject({
      creator: {
        "@type": "Person",
        "@id": ids.person,
        name: "Nick Hand",
      },
      maintainer: { "@id": ids.person },
      publisher: {
        "@type": "Person",
        "@id": ids.person,
        name: "Nick Hand",
      },
      license: {
        "@type": "CreativeWork",
        name: "Licensing and terms for dashboard data",
        url: `${canonicalUrl}/data#terms-methods`,
      },
    });
    expect(createDashboardDatasetProvenance(ids)).not.toHaveProperty(
      "isPartOf",
    );
  });

  it("models external sources as links instead of republishing their datasets", () => {
    expect(createCourtSourceEntity(ids)).toMatchObject({
      "@type": "WebPage",
      "@id": "https://ujsportal.pacourts.us/CaseSearch#webpage",
    });
  });
});
