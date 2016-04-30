
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
    data = data.toString();
    console.log(`SO: ${data.substring(0, data.length-1)}`);
  });

  sumobot.stderr.on("data", (data) => {
    data = data.toString();
    console.log(`SE: ${data.substring(0, data.length-1)}`);
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

