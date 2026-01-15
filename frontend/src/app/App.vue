<template>
  <v-app theme="dark">
    <v-main>
      <router-view></router-view>
    </v-main>
  </v-app>
</template>

<script setup lang="ts"></script>

<style>
@import url("https://fonts.googleapis.com/css?family=Open+Sans");
@import url("https://fonts.googleapis.com/css?family=Montserrat");

html,
body {
  margin: 0;
  padding: 0;
  background-color: rgb(var(--v-theme-background));
}
</style>
