# !/usr/bin/env python
# -*- encoding: utf-8 -*-
# @File: main.py
# @Author: Max
import time
from pathlib import Path

import cv2
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from resources.bpocr import TextSystem, draw_text_det_res

# 实例化模型
det_model_path = 'resources/models/ch_ppocr_mobile_v2.0_det_infer.onnx'
cls_model_path = 'resources/models/ch_ppocr_mobile_v2.0_cls_infer.onnx'
rec_model_path = 'resources/models/ch_ppocr_mobile_v2.0_rec_infer.onnx'

text_sys = TextSystem(det_model_path,
                      rec_model_path,
                      use_angle_cls=True,
                      cls_model_path=cls_model_path)

# 设置允许的文件格式
ALLOWED_EXTENSIONS = {'png', 'jpg', 'JPG', 'PNG', 'bmp', 'jpeg', 'gif', 'tif'}
app = Flask(__name__)

# 设置上传文件大小
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10M

# 设置静态文件缓存过期时间
# app.send_file_max_age_default = TimedeltaFormat(seconds=10)

def make_directory(directory_path):
    if not isinstance(directory_path, Path):
        directory_path = Path(directory_path)
    directory_path.mkdir(parents=True, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


@app.route('/ocr', methods=['POST', 'GET'])
def ocr():
    if request.method == 'POST':
        f = request.files['file']

        if not (f and allowed_file(f.filename)):
            return jsonify({"error": 1001, "msg": "only support png、PNG、\
                            jpg、JPG、bmp、JPEG、gif"})

        time_stamp = time.strftime('%Y-%m-%d-%H-%M-%S',
                                   time.localtime(time.time()))
        img_name = f"{time_stamp}_{secure_filename(f.filename)}"

        root_path = Path(__file__).resolve().parent
        static_directory = root_path / 'static'

        raw_directory = static_directory / 'images'
        make_directory(raw_directory)

        infer_directory = static_directory / 'inference_results'
        make_directory(infer_directory)

        upload_path = str(raw_directory / f'raw_{img_name}')
        f.save(upload_path)

        t1 = time.time()
        dt_boxes, rec_res, img = text_sys(upload_path)
        t2 = time.time()

        rec_res = list(zip(range(len(rec_res)), rec_res))

        det_im = draw_text_det_res(dt_boxes, img)
        det_path = f'inference_results/det_{img_name}'

        cv2.imwrite(str(static_directory / det_path), det_im)

        return render_template('index_ok.html',
                               det_img_path=det_path,
                               rec_res=rec_res,
                               time=str(f'{t2-t1:.3f}'),
                               width='100%',
                               height='100%',
                               )
    return render_template('index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9003, debug=False, processes=True)