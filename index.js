
"use strict";

let gpg = require("gpg");
let path = require("path");
let child_process = require("child_process");

const spawnRobot = (env) => {
  let sumobot = child_process.spawn(
    path.join(".", "bin", "hubot"),
    [ "--adapter", "slack" ],
    {
      "env": Object.assign({}, process.env, env)
    }
  );

  sumobot.stdout.on("data", (data) => {
    data = data.toString().split("\n");
    let i;
    for(i=0; i<data.length - 1; ++i) {
      console.log(`SO: ${data[i]}`);
    }
    let last = data[data.length - 1];
    if(last !== "") {
      console.log(`SO: ${last}`);
    }
  });

  sumobot.stderr.on("data", (data) => {
    data = data.toString().split("\n");
    let i;
    for(i=0; i<data.length - 1; ++i) {
      console.log(`SE: ${data[i]}`);
    }
    let last = data[data.length - 1];
    if(last !== "") {
      console.log(`SE: ${last}`);
    }
  });

  sumobot.on("close", (code) => {
    if(code == 42) { /* restart */
      spawnRobot(env);
    } else {
      console.log(`exited with code: ${code}`);
    }
  });
};

gpg.decryptFile(
  path.join("files", "bot-environment.json.asc"),
  (_, buffer) => spawnRobot(JSON.parse(buffer.toString()))
);

