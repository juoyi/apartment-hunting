# coding=utf-8


from flask import Flask


app = Flask(__name__)
# app.config['DEBUG'] = True


@app.route("/")
def index():
    return "index page"

if __name__ == "__main__":
    app.run(debug=True)
