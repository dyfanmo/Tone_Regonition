import sys
import wave
import librosa
import numpy as np
import pandas as pd
from tqdm import tqdm
from os import listdir
import hanzidentifier
import os.path as path
import soundfile as sf
from pydub import AudioSegment
from sklearn.decomposition import PCA
from pydub.silence import split_on_silence
from sklearn.ensemble import IsolationForest

ROOT_DIR = path.abspath(path.join(__file__ ,"../../.."))
sys.path.insert(1, ROOT_DIR)
import src.utils as utils

pd.options.mode.chained_assignment = None

DATA_PATH = f"{ROOT_DIR}/data"
AUDIO_PATH = f"{ROOT_DIR}/data/raw/Audio"
CLN_AUDIO_PATH = f"{ROOT_DIR}/data/processed/Audio/audio_cln"


def remove_silence(df):
    for index in tqdm(df.index):
        id_i = df['id'].loc[index]
        song = AudioSegment.from_wav(f"{AUDIO_PATH}/{id_i}")
        cln_files = listdir(CLN_AUDIO_PATH)

        if id_i not in cln_files:
            chunks = split_on_silence(
                song,
                min_silence_len=300,
                silence_thresh=-30,
                keep_silence=300
            )

            if chunks:
                for i, chunk in enumerate(chunks):
                    silence_chunk = AudioSegment.silent(duration=200)
                    audio_chunk = silence_chunk + chunk + silence_chunk
                    normalized_chunk = utils.match_target_amplitude(audio_chunk, -20.0)

                    normalized_chunk.export(
                        f"{CLN_AUDIO_PATH}/{id_i}",
                        bitrate="192k",
                        format="wav"
                    )

            else:
                df.drop(index=index, inplace=True)
    df['new_nframes'] = df['id'].apply(lambda f: wave.open(f'{CLN_AUDIO_PATH}/{f}').getnframes())
    df['new_duration'] = df['id'].apply(lambda f: wave.open(f'{CLN_AUDIO_PATH}/{f}').getnframes() /
                                            wave.open(f'{CLN_AUDIO_PATH}/{f}').getframerate())
    return df


def audio_augmentation(df):
    df_ag = pd.DataFrame()

    for index in tqdm(df.index):
        row = df.loc[index]
        path = f'{ROOT_DIR}/data/processed/Audio/audio_cln/{row.id}'
        ag_path = f'{ROOT_DIR}/data/processed/Audio/audio_aug'
        ag_files = listdir(ag_path)

        id_name = row.id[6:]
        id_wn = f'audioWN_{id_name}'
        id_dp = f'audioDP_{id_name}'
        id_hi = f'audioHF_{id_name}'
        id_rl = f'audioRL_{id_name}'

        if id_rl not in ag_files:
            wav, sr = librosa.load(path)

            wn = np.random.randn(len(wav))
            wav_wn = wav + 0.005 * wn
            wav_dp = utils.change_pitch(wav, sr, deep=True)
            wav_hi = utils.change_pitch(wav, sr, deep=False)
            wav_rl = np.roll(wav, sr)

            wav_list = [(id_wn, wav_wn), (id_dp, wav_dp), (id_hi, wav_hi), (id_rl, wav_rl)]

            for wav_i in wav_list:
                id_i = wav_i[0]
                row['id'] = id_i
                row['audio_type'] = id_i[5:7]
                df_ag = pd.concat([df_ag, pd.DataFrame(row).T])
                sf.write(f'{ag_path}/{id_i}', wav_i[1], sr)
        else:
            for id_i in [id_wn, id_dp, id_hi, id_rl]:
                row['id'] = id_i
                row['audio_type'] = id_i[5:7]
                df_ag = pd.concat([df_ag, pd.DataFrame(row).T])

    df['audio_type'] = 'CL'
    df = pd.concat([df, df_ag])
    df.reset_index(drop=True, inplace=True)
    print(f"# Samples Added: {len(df_ag)} ")
    return df


def speech_recognition_assessment(df):
    df = df.sample(frac=1)
    df['transcripts'] = np.nan
    df['pred_tone'] = np.nan
    df['sound_quality'] = np.nan
    audio_checked = []
    old_df = {}
    df_cln = pd.DataFrame()

    try:
        audio_checked = utils.load_object(f'{DATA_PATH}/processed/audio_checked.pkl')
        old_df = pd.read_pickle(f'{DATA_PATH}/processed/audio_cln.pkl')
    except:
        pass
    for index in tqdm(df.index):
        ser_i = df.loc[index]
        id_i = ser_i.id

        if id_i in audio_checked:
            df.drop(index=index, inplace=True)
            row = old_df.loc[old_df['id'] == id_i]
            df_cln = pd.concat([df_cln, row])
        else:
            path = utils.get_audio_path(ser_i)
            transcripts = utils.speech_to_text(path)

            word = df['word'].loc[index]
            tone = df['tone'].loc[index]

            if transcripts:
                cln_transcripts = []
                for text in transcripts:
                    if pd.notnull(text):
                        if len(text) == 1:
                            if hanzidentifier.has_chinese(text):
                                cln_transcripts.append(text)

                if cln_transcripts:
                    df['transcripts'].loc[index] = cln_transcripts
                    pred_tones = [utils.text_to_tone(x) for x in cln_transcripts]
                    if word in cln_transcripts:
                        df['sound_quality'].loc[index] = 0
                        df['pred_tone'].loc[index] = tone
                    elif tone in pred_tones:
                        df['sound_quality'].loc[index] = 1
                        df['pred_tone'].loc[index] = tone
                    else:
                        df['sound_quality'].loc[index] = 2
                        df['pred_tone'].loc[index] = pred_tones[0]  # word with the highest confidence score
                else:
                    df.drop(index=index, inplace=True)

            else:
                df.drop(index=index, inplace=True)
        audio_checked.append(id_i)

    if audio_checked:
        df = pd.concat([df, df_cln])

    df = df[df.new_duration < 2]
    df.reset_index(drop=True, inplace=True)
    utils.save_object(audio_checked, f'{DATA_PATH}/processed/audio_checked.pkl')
    df.to_pickle(f'{DATA_PATH}/processed/audio_cln.pkl')
    return df


def pca_anomaly_detection(df):
    fft_all = []
    for index in tqdm(df.index):
        ser_i = df.loc[index]
        file_path = utils.get_audio_path(ser_i)
        specgram = utils.get_melspectrogram_db(file_path, duration=2)
        fft_all.append(specgram)

    fft_all = np.array(fft_all)
    # Normalization
    fft_all = (fft_all - np.mean(fft_all, axis=0)) / np.std(fft_all, axis=0)
    fft_all = fft_all.reshape(fft_all.shape[0], fft_all.shape[1] * fft_all.shape[2])

    # Dim reduction
    pca = PCA(n_components=3)
    fft_all = pca.fit_transform(fft_all)
    df['pca_X'] = fft_all[:, 0]
    df['pca_Y'] = fft_all[:, 1]
    df['pca_Z'] = fft_all[:, 2]

    try:
        audio_type = pd.get_dummies(df.audio_type).to_numpy()
        fft_all = np.hstack([fft_all, audio_type])
    except:
        pass

    clf = IsolationForest(n_estimators=200, max_samples='auto', contamination=float(.03),
                          max_features=1.0, bootstrap=False, n_jobs=-1, random_state=42, verbose=0)
    clf.fit(fft_all)

    pred = clf.predict(fft_all)
    df['anomaly'] = pred
    df = df.sample(frac=1)
    return df


def sample_tone_per(df, tone_per):
    df_len = len(df)
    original_df = df.copy()

    tone1 = df[df.tone == 1]
    tone2 = df[df.tone == 2]
    tone3 = df[df.tone == 3]
    tone4 = df[df.tone == 4]

    for i in range(df_len):
        try:
            sample4 = tone4.sample(int(tone_per[4] * df_len))
            sample3 = tone3.sample(int(tone_per[3] * df_len))
            sample2 = tone2.sample(int(tone_per[2] * df_len))
            sample1 = tone1.sample(int(tone_per[1] * df_len))
            break
        except:
            df_len -= 1

    df = pd.concat([sample1, sample2, sample3, sample4])
    df = df.sample(frac=1)
    df.reset_index(drop=True, inplace=True)
    print(f"# Samples Removed: {len(original_df) - len(df)} ")
    return df


if __name__ == "__main__":

    audio_data = pd.read_pickle(f'{ROOT_DIR}/data/processed/audio_df.pkl')
    audio_data = audio_data.dropna()

    print('Removing Silence!')
    df_count = len(audio_data)
    audio_data = remove_silence(audio_data)
    audio_data = audio_data[audio_data.new_duration < 2]
    print(f"# Samples Removed: {df_count - len(audio_data)} ")

    print('Data Augmentation!')
    audio_data_ag = audio_augmentation(audio_data)

    print('Removing Outliers!')
    df_count = len(audio_data_ag)
    audio_pca = pca_anomaly_detection(audio_data_ag)
    audio_inlier = audio_pca[audio_pca['anomaly'] == 1]
    audio_inlier.reset_index(inplace=True, drop=True)
    print(f"# Samples Removed: {df_count - len(audio_inlier)} ")

    print('Speech Recognition Assessment!')
    df_count = len(audio_inlier)
    audio_cln = speech_recognition_assessment(audio_inlier)
    audio_best = audio_cln[audio_cln['sound_quality'] <= 1]
    print(f"# Samples Removed: {df_count - len(audio_best)} ")

    print('Sampling Data!')
    chinese_words = utils.extract_words()
    tone_per = utils.get_tone_per(chinese_words)
    audio_pr = sample_tone_per(audio_best, tone_per)

    audio_pr.to_pickle(f"{ROOT_DIR}/data/processed/audio_pr.pkl")
    print(f"# Data Set Size: {len(audio_pr)}")
    print('Process Done!')
