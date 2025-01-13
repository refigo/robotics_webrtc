import express from "express";

const app = express();

app.set("view engine", "pug");
app.set("views", __dirname)


const handleListen = () => console.log(`Listening on: http://localhost:3000`);
app.listen(3000, handleListen);
