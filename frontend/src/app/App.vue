<template>
  <v-app theme="dark">
    <v-main>
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <keep-alive>
            <component :is="Component" :key="$route.path" />
          </keep-alive>
        </transition>
      </router-view>
    </v-main>
  </v-app>
</template>

<script setup lang="ts"></script>

<style>
@import url("https://fonts.googleapis.com/css?family=Open+Sans");
@import url("https://fonts.googleapis.com/css?family=Montserrat");
</style>
