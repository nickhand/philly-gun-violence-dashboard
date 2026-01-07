<template>
  <div class="about-page-wrapper">
    <dashboard-navbar
      :data-years="[]"
      :selected-year="null"
      :show-overlay="false"
    />
    <section class="about-page">
      <!-- Data Sources -->
      <div class="mt-0 mt-md-10">
        <h2 class="text-h4 mb-4">Data</h2>

        <!-- Disclaimer -->
        <p class="mb-4">
          This application was originally developed by Nick Hand for the
          Philadelphia City Controller's Office. After leaving the office, it
          was migrated to his personal website. The dashboard relies on publicly
          available data from the City of Philadelphia and Pennsylvania's
          Unified Judicial System. The data sources are:
        </p>

        <!-- List original data sources -->
        <ul class="pl-0">
          <li class="mb-2">
            <a
              href="https://www.opendataphilly.org/dataset/shooting-victims"
              target="_blank"
              rel="noopener noreferrer"
              class="about-link"
            >
              <v-icon icon="mdi-open-in-new" size="small" />
              <span class="ml-2">Shooting victims data</span>
            </a>
            from the City of Philadelphia's open data program, posted on
            OpenDataPhilly.org
          </li>
          <li class="mb-2">
            <a
              href="https://www.phillypolice.com/crime-data/crime-statistics/#homicide_numbers"
              target="_blank"
              rel="noopener noreferrer"
              class="about-link"
            >
              <v-icon icon="mdi-open-in-new" size="small" />
              <span class="ml-2">Total homicide count</span>
            </a>
            from the Philadelphia Police Department's crime statistics website
          </li>
          <li class="mb-2">
            <a
              href="https://ujsportal.pacourts.us/CaseSearch"
              target="_blank"
              rel="noopener noreferrer"
              class="about-link"
            >
              <v-icon icon="mdi-open-in-new" size="small" />
              <span class="ml-2">Information on court cases</span>
            </a>
            from the web portal for the Unified Judicial System of Pennsylvania
          </li>
        </ul>
      </div>

      <!-- Methods -->
      <div class="mt-16">
        <h2 class="text-h4 mb-4">Methods</h2>
        <p class="mb-4">
          The data for shooting victims in this application is automatically
          updated daily. As noted on Open Data Philly's
          <a
            href="https://metadata.phila.gov/#home/datasetdetails/5719551277d6389f3005a610/representationdetails/5719551277d6389f3005a614/"
            target="_blank"
            rel="noopener noreferrer"
            class="about-link"
          >
            documentation page </a
          >:
        </p>
        <p class="mb-4 ml-12 font-italic">
          The shooting victims data source is maintained by the Statistics Unit
          within the Philadelphia Police Department (only staffed on weekdays).
          The shooting victim information is entered manually to the source
          database by examining investigative reports from Detectives. Due to
          this manual process, shooting victim data are updated on Open Data
          Philly daily by ~10:30 am.
        </p>

        <p class="mb-4">
          It is important to note that the total homicide count, as given on the
          Philadelphia Police Department's crime statistics website includes
          homicides of all kinds, rather than just firearm-related homicides.
        </p>

        <p class="mb-4">
          All data presented in this application is preliminary and may not
          agree with criminal incident data publicly available from other
          sources. In particular, information on fatal shootings from the
          shooting victims dataset may underestimate the total number of
          firearm-related homicides.
        </p>

        <p class="mb-4">
          Information on court cases associated with shooting incidents is
          updated on a weekly basis. Court case information is determined by
          searching for the police incident number for each shooting incident
          (the "DC number") using the Philadelphia Municipal Court interface of
          the Unified Judicial System of Pennsylvania web portal.
        </p>

        <p class="mb-4">
          The software behind this application is publicly available on
          <a
            href="https://github.com/nickhand"
            target="_blank"
            rel="noopener noreferrer"
            class="about-link"
          >
            Nick Hand's GitHub </a
          >:
        </p>
        <ul class="pl-0">
          <li class="mb-2">
            <a
              href="https://github.com/nickhand/philly-gun-violence-dashboard"
              target="_blank"
              rel="noopener noreferrer"
              class="about-link"
            >
              <v-icon icon="mdi-open-in-new" size="small" class="mr-2" />
              <span class="url-break">
                https://github.com/nickhand/philly-gun-violence-dashboard
              </span>
            </a>
          </li>
        </ul>
      </div>

      <!-- Feedback -->
      <div class="mt-16">
        <h2 class="text-h4 mb-4">Application Feedback</h2>
        <p class="mb-4">
          If you've noticed a bug in this application or have suggestions for
          how to make it better, please send an email to
          <a href="mailto:nicholas.adam.hand@gmail.com" class="about-link">
            nicholas.adam.hand@gmail.com </a
          >.
        </p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import DashboardNavbar from "@/features/dashboard/components/DashboardNavbar.vue";
</script>

<style scoped>
.about-page-wrapper {
  background-color: rgb(var(--v-theme-background));
  min-height: 100vh;
}

.about-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 60px 20px;
  text-align: left;
  color: rgb(var(--v-theme-primary));
}

.about-page h2 {
  font-family: var(--heading-font-family);
}

.about-page ul {
  list-style-type: none;
}

.about-link {
  color: #7ab5e5;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.about-link:hover {
  text-decoration: underline;
}

.url-break {
  word-wrap: break-word;
}
</style>
