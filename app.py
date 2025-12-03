from flask import Flask, render_template, redirect,  url_for, request, session, flash, jsonify
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_scss import Scss
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from PIL import Image
import pytesseract
import os

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

app = Flask(__name__)
app.secret_key = "I'm-not-telling-you"
Scss(app)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config['UPLOAD_FOLDER'] = 'static/uploads'
db = SQLAlchemy(app)
#Database models
class ImageExtracted(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	userid = db.Column(db.String(20), nullable=True)
	filename = db.Column(db.String(70))
	text_extracted = db.Column(db.String, nullable=True)
	words = db.Column(db.Integer, default=0)
	date_created = db.Column(db.DateTime, default = datetime.now)#(datetime.timezone.utc))
	filesize = db.Column(db.String, nullable=True)
	
	def __repr__(self) -> str:
		return f"Image{self.id}"
	
class User(db.Model):
	userid = db.Column(db.Integer, primary_key=True)
	username = db.Column(db.String(30), unique=True, nullable=False)
	email = db.Column(db.String(120), unique=True, nullable=False)
	password_hash = db.Column(db.String(128), nullable=False)
	date_created = db.Column(db.DateTime, default=datetime.now)

	def set_password(self, password):
		self.password_hash = generate_password_hash(password)
	
	def check_password(self, password):
		return check_password_hash(self.password_hash, password)

	def __repr__(self) -> str:
		return f"User<{self.username}>"
	


def login_required(f):
	@wraps(f)
	def wrap(*args, **kwargs):
		
		if 'logged_in' in session:
			return f(*args, **kwargs)
		else:
			flash("You need to login first")
			return redirect(url_for('login'))
	return wrap

#Homepage
@app.route("/", methods=["GET", "POST"])
def index():
	 #Add an Image
	if request.method == "POST":
		#Check if file was uploaded
		if 'imagefile' not in request.files:
			flash('No file part', 'danger')
			return redirect(request.url)
		
		file = request.files['imagefile']

		if file.filename == '':
			flash('No selected file', 'danger')
			return redirect(request.url)

		if file:
			#secure the filename and save it
			filename = secure_filename(file.filename)
			filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
			file.save(filepath)

			#get file size
			filesize = os.path.getsize(filepath)
			filesize_str = f"{filesize / 1024:.2f} KB" #format as KB

			#create a new database record
			new_image = ImageExtracted(
				filename=filename, 
				filesize=filesize_str,
				date_created=datetime.now(),
				userid=session.get('user_id') if 'logged_in' in session else 'temp'
			)

			db.session.add(new_image)
			db.session.commit()

			flash("Image uploaded successfully!", 'success')
			return redirect(url_for("index"))
	cutoff_time = datetime.now() - timedelta(minutes=10)
	
	images = ImageExtracted.query.order_by(ImageExtracted.date_created.desc()).all()

	if 'logged_in' in session:
		images = ImageExtracted.query.filter(ImageExtracted.userid == session.get('user_id'), ImageExtracted.date_created >= cutoff_time).order_by(ImageExtracted.date_created.desc()).all()
		return render_template("index.html", images=images, logged_in=True)
	else:

		images = ImageExtracted.query.filter(ImageExtracted.userid == 'temp', ImageExtracted.date_created >= cutoff_time).order_by(ImageExtracted.date_created.desc()).all()
		return render_template("index.html", images=images, logged_in=False)

#Login Route
@app.route('/login', methods=['POST', 'GET'])
def login():
	error = None

	if 'logged_in' in session:
		return redirect(url_for('index'))
	
	if request.method == "POST":

		identifier = request.form.get('username')
		password = request.form.get('password')
		user = User.query.filter((User.username == identifier ) | (User.email == identifier)).first()

		if not user or not user.check_password(password):
			error = 'Invalid credentials. Please try again'
		else:
			session['logged_in'] = True
			session['user_id'] = user.userid
			session['username'] = user.username
			flash("You were just logged in", 'success')

			return redirect(url_for('index'))
		
	return render_template('login.html', error=error)

@app.route('/logout')
def logout():

	session.pop('logged_in', None)
	flash("You were just logged out", 'danger')
	return redirect(url_for('index'))

@app.route('/history')
@login_required
def history():

	current_user_id = session.get('user_id')


	files = ImageExtracted.query.filter_by(userid=current_user_id).order_by(ImageExtracted.date_created.desc()).all()

	if not files:
		flash("Nothing yet", 'info')
	return render_template('history.html', files=files)

@app.route('/register', methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        if not username or not email or not password:
            error = "Please fill all required fields"
        elif password != password_confirm:
            error = "Passwords do not match"
        elif User.query.filter_by(username=username).first():
            error = "Username already taken."
        elif User.query.filter_by(email=email).first():
            error = "Email already registered, login or try another email"
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            flash("Registration successful. You can now login.", 'success')
            return redirect(url_for('login'))

    return render_template('register.html', error=error)

#NO-PAGE Routes
#Cleanup route
@app.route('/cleanup_temp', methods=['POST'])
def cleanup_temp():
    try:
        cutoff_time = datetime.now() - timedelta(minutes=30)
        temp_images = ImageExtracted.query.filter(
            ImageExtracted.userid == 'temp',
            ImageExtracted.date_created < cutoff_time
        ).all()

        for image in temp_images:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
            if os.path.exists(filepath):
                os.remove(filepath)
            db.session.delete(image)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
	

#Extract route
@app.route("/extract/<int:image_id>", methods=["POST"] )
def extract_text(image_id):
	image_record = ImageExtracted.query.get_or_404(image_id)

	filepath = os.path.join(app.config['UPLOAD_FOLDER'], image_record.filename)

	try:
		#Use pytesseract to extract text
		extracted_text = pytesseract.image_to_string(Image.open(filepath))

		#update database record
		image_record.text_extracted = extracted_text
		image_record.words = len(extracted_text.split())
		db.session.commit()

		#return the extracted text as JSON
		return jsonify({
			'success':True,
			'text': extracted_text,
			'words': image_record.words
		})
	except Exception as e:
		return jsonify({'success': False, 'error':str(e)})
	
#Delete image route
@app.route("/delete/<int:image_id>", methods=["POST"])
def delete(image_id):
	image_record = ImageExtracted.query.get_or_404(image_id)
	try:
		#delete the image file
		filepath = os.path.join(app.config['UPLOAD_FOLDER'], image_record.filename)
		if os.path.exists(filepath):
			os.remove(filepath)

		#delete the database record
		db.session.delete(image_record)
		db.session.commit()

		return jsonify({
			'success':True,
			'message': 'Image record deleted successfully.'
		})
	except Exception as e:
		return jsonify({'success': False, 'error':str(e)})

if __name__ == '__main__':
	with app.app_context():
		db.create_all()
	app.run(debug=True)
	