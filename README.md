# Tone Regonition

Train a machine learning model to classify tones in Chinese through audio files.

# Prerequisites

## 1) Hardware
* All experiments in paper were conducted with single K80 GPU (24GB).
* You might want to adjust the size of batch and models for your memory size.

## 2) Software
* Ubuntu 16.04 or 18.04 (Not tested with other versions, but might work)
* Python 3.6+
  - `pip install -r requirements.txt` 


## 3) Data

```sh
# Download Audio files.
mkdir data/raw
wget https://www.dropbox.com/s/3cd5lxq1x7h1ulq/Audio.zip?dl=0
unzip Audio.zip
mv Audio data/raw

# Request more data. Insert api key from https://api.forvo.com/
python make_dataset.py --api_key=''

# Clean the audio files.
python clean_data.py

# Prepare training data.
python data_loader.py 
```

# Run
You can see more configurations in [configs](configs) folder

## Train
```sh
python train.py --model='ALL' --epochs=50
```

## Evaluation
```sh
python evaluate.py 