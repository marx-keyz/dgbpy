#__________________________________________________________________________
#
# (C) dGB Beheer B.V.; (LICENSE) http://opendtect.org/OpendTect_license.txt
# Author:        A. Huck
# Date:          Nov 2018
#
# _________________________________________________________________________
# various tools machine learning using Keras platform
#

import os
import re
from datetime import datetime
import numpy as np
import math

from odpy.common import log_msg, get_log_file, redirect_stdout, restore_stdout
import dgbpy.keystr as dgbkeys
import dgbpy.hdf5 as dgbhdf5


os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'
from keras.callbacks import (EarlyStopping,LearningRateScheduler)
withtensorboard = True
if 'KERAS_WITH_TENSORBOARD' in os.environ:
  withtensorboard = not ( os.environ['KERAS_WITH_TENSORBOARD'] == False or \
                          os.environ['KERAS_WITH_TENSORBOARD'] == 'No' )
if withtensorboard:
  from keras.callbacks import TensorBoard

platform = (dgbkeys.kerasplfnm,'Keras (tensorflow)')
mltypes = (\
            ('lenet','LeNet - Malenov'),\
            ('unet','U-Net'),\
#            ('squeezenet','SqueezeNet'),\
#            ('other','MobilNet V2'),\
          )

cudacores = [ '8', '16', '32', '48', '64', '96', '128', '144', '192', '256', \
              '288',  '384',  '448',  '480',  '512',  '576',  '640',  '768', \
              '896',  '960',  '1024', '1152', '1280', '1344', '1408', '1536', \
              '1664', '1792', '1920', '2048', '2176', '2304', '2432', '2496', \
              '2560', '2688', '2816', '2880', '2944', '3072', '3584', '3840', \
              '4352', '4608', '4992', '5120' ]

def getMLPlatform():
  return platform[0]

def getUIMLPlatform():
  return platform[1]

def getUiModelTypes():
  return dgbkeys.getNames( mltypes )

def isLeNet( mltype ):
  return mltype == mltypes[0][0] or mltype == mltypes[0][1]

def isUnet( mltype ):
  return mltype == mltypes[1][0] or mltype == mltypes[1][1]

def isSqueezeNet( mltype ):
  return mltype == mltypes[2][0] or mltype == mltypes[2][1]

def isMobilNetV2( mltype ):
  return mltype == mltypes[3][0] or mltype == mltypes[3][1]

firstconvlayernm = 'conv_layer1'
lastlayernm = 'pre-softmax_layer'
keras_dict = {
  dgbkeys.decimkeystr: False,
  'nbchunk': 10,
  'epoch': 15,
  'batch': 32,
  'patience': 5,
  'learnrate': 0.01,
  'epochdrop': 5,
  'type': mltypes[0][0],
}

def getParams( dodec=keras_dict[dgbkeys.decimkeystr], nbchunk=keras_dict['nbchunk'],
               epochs=keras_dict['epoch'],
               batch=keras_dict['batch'], patience=keras_dict['patience'],
               learnrate=keras_dict['learnrate'],
               epochdrop=keras_dict['epochdrop'],nntype=keras_dict['type'] ):
  ret = {
    dgbkeys.decimkeystr: dodec,
    'nbchunk': nbchunk,
    'epoch': epochs,
    'batch': batch,
    'patience': patience,
    'learnrate': learnrate,
    'epochdrop': epochdrop,
    'type': nntype
  }
  if not dodec:
    ret['nbchunk'] = 1
  return ret

# Function that takes the epoch as input and returns the desired learning rate
# input_int: the epoch that is currently being entered
def adaptive_schedule(initial_lrate=keras_dict['learnrate'],
                      epochs_drop=keras_dict['epochdrop']):
  def adaptive_lr(input_int):
    drop = 0.5
    return initial_lrate * math.pow(drop,
                                    math.floor((1+input_int)/epochs_drop))
    # return the learning rate (quite arbitrarily decaying)
  return LearningRateScheduler(adaptive_lr)

def cross_entropy_balanced(y_true, y_pred):
  from keras.models import K
  from keras.optimizers import tf
  _epsilon = _to_tensor(K.epsilon(), y_pred.dtype.base_dtype)
  y_pred   = tf.clip_by_value(y_pred, _epsilon, 1 - _epsilon)
  y_pred   = tf.log(y_pred/ (1 - y_pred))

  y_true = tf.cast(y_true, tf.float32)
  count_neg = tf.reduce_sum(1. - y_true)
  count_pos = tf.reduce_sum(y_true)
  beta = count_neg / (count_neg + count_pos)
  pos_weight = beta / (1 - beta)
  cost = tf.nn.weighted_cross_entropy_with_logits(logits=y_pred, targets=y_true, pos_weight=pos_weight)
  cost = tf.reduce_mean(cost * (1 - beta))
  return tf.where(tf.equal(count_pos, 0.0), 0.0, cost)

def _to_tensor(x, dtype):
  from keras.optimizers import tf
  x = tf.convert_to_tensor(x)
  if x.dtype != dtype:
    x = tf.cast(x, dtype)
  return x

def getLayer( model, name ):
  for lay in model.layers:
    if lay.get_config()['name'] == name:
      return lay
  return None

def getDataFormat( model ):
  convlay1_config = getLayer(model,firstconvlayernm).get_config()
  return convlay1_config['data_format']

def getCubeletStepout( model ):
  convlay1_config = getLayer(model,firstconvlayernm).get_config()
  data_format = getDataFormat( model )
  if data_format == 'channels_first':
    cubeszs = convlay1_config['batch_input_shape'][2:]
  elif data_format == 'channels_last':
    cubeszs = convlay1_config['batch_input_shape'][1:-1]
  stepout = tuple()
  for cubesz in cubeszs:
    stepout += (int((cubesz-1)/2),)
  return (stepout,cubeszs)

def getNrClasses( model ):
  return getLayer(model,lastlayernm).get_config()['units']

def getLogDir( basedir, args ):
  logdir = basedir
  if not withtensorboard or logdir == None or not os.path.exists(logdir):
    return None

  if dgbkeys.surveydictstr in args:
    jobnm = args[dgbkeys.surveydictstr][0] + '_run'
  else:
    jobnm = 'run'

  nrsavedruns = 0
  with os.scandir(logdir) as it:
    for entry in it:
      if entry.name.startswith(jobnm) and entry.is_dir():
        nrsavedruns += 1
  logdir = os.path.join( logdir, jobnm+str(nrsavedruns+1)+'_'+'m'.join( datetime.now().isoformat().split(':')[:-1] ) )
  return logdir

def getDefaultModel(setup,type=keras_dict['type'],
                    learnrate=keras_dict['learnrate'],
                    data_format='channels_first'):
  nrinputs = dgbhdf5.get_nr_attribs(setup)
  isclassification = setup[dgbhdf5.classdictstr]
  if isclassification:
    nroutputs = len(setup[dgbkeys.classesdictstr])
  else:
    nroutputs = 1
  stepout = setup[dgbkeys.stepoutdictstr]
  try: 
    steps = (nrinputs,2*stepout[0]+1,2*stepout[1]+1,2*stepout[2]+1)
  except TypeError:
    steps = (nrinputs,1,1,2*stepout+1)

  if isLeNet( type ):
    return getDefaultLeNet(setup,isclassification,steps,nroutputs,
                           learnrate=learnrate,data_format=data_format)
  elif ifUnet( type ):
    return getDefaultUnet(setup,isclassification,steps,nroutputs,
                          learnrate=learnrate,data_format=data_format)
  else:
    return None

def getDefaultLeNet(setup,isclassification,steps,nroutputs,
                    learnrate=keras_dict['learnrate'],
                    data_format='channels_first'):
  redirect_stdout()
  import keras
  restore_stdout()
  from keras.layers import (Activation,Conv3D,Dense,Dropout,Flatten)
  from keras.layers.normalization import BatchNormalization
  from keras.models import Sequential

  model = Sequential()
  model.add(Conv3D(50, (5, 5, 5), strides=(4, 4, 4), padding='same', \
            name=firstconvlayernm,input_shape=steps,data_format=data_format))
  model.add(BatchNormalization())
  model.add(Activation('relu'))
  model.add(Conv3D(50, (3, 3, 3), strides=(2, 2, 2), padding='same', name='conv_layer2', data_format=data_format))
  model.add(Dropout(0.2))
  model.add(BatchNormalization())
  model.add(Activation('relu'))
  model.add(Conv3D(50, (3, 3, 3), strides=(2, 2, 2), padding='same', name='conv_layer3',data_format=data_format))
  model.add(Dropout(0.2))
  model.add(BatchNormalization())
  model.add(Activation('relu'))
  model.add(Conv3D(50, (3, 3, 3), strides=(2, 2, 2), padding='same', name='conv_layer4',data_format=data_format))
  model.add(Dropout(0.2))
  model.add(BatchNormalization())
  model.add(Activation('relu'))
  model.add(Conv3D(50, (3, 3, 3), strides=(2, 2, 2), padding='same', name='conv_layer5',data_format=data_format))
  model.add(Flatten())
  model.add(Dense(50,name = 'dense_layer1'))
  model.add(BatchNormalization())
  model.add(Activation('relu'))
  model.add(Dense(10,name = 'attribute_layer'))
  model.add(BatchNormalization())
  model.add(Activation('relu'))
  model.add(Dense(nroutputs, name=lastlayernm))
  model.add(BatchNormalization())
  model.add(Activation('softmax'))

# initiate the model compiler options
  metrics = ['accuracy']
  if isclassification:
    opt = keras.optimizers.adam(lr=learnrate)
    if nroutputs > 2:
      loss = 'categorical_crossentropy'
    else:
      loss = 'binary_crossentropy'
  else:
    opt = keras.optimizers.RMSprop(lr=learnrate)
#    set_epsilon( 1 )
    from keras import backend as K
    def root_mean_squared_error(y_true, y_pred):
      return K.sqrt(K.mean(K.square(y_pred - y_true)))
    loss = root_mean_squared_error

# Compile the model with the desired optimizer, loss, and metric
  model.compile(optimizer=opt,loss=loss,metrics=metrics)
  return model

def getDefaultUnet(setup,isclassification,steps,nroutputs,
                    learnrate=keras_dict['learnrate'],
                    data_format='channels_first'):
  redirect_stdout()
  import keras
  restore_stdout()
  from keras.layers import (concatenate,Conv3D,Input,MaxPooling3D,UpSampling3D)
  from keras.models import Model
  from keras.optimizers import Adam

  if data_format == 'channels_first':
    stepout = (steps[1],steps[2],steps[3],1)
  else:
    stepout = steps

  inputs = Input(stepout)

  conv1 = Conv3D(2, (3,3,3), activation='relu', padding='same')(inputs)
  conv1 = Conv3D(2, (3,3,3), activation='relu', padding='same')(conv1)
  pool1 = MaxPooling3D(pool_size=(2,2,2))(conv1)

  conv2 = Conv3D(4, (3,3,3), activation='relu', padding='same')(pool1)
  conv2 = Conv3D(4, (3,3,3), activation='relu', padding='same')(conv2)
  pool2 = MaxPooling3D(pool_size=(2,2,2))(conv2)

  conv3 = Conv3D(8, (3,3,3), activation='relu', padding='same')(pool2)
  conv3 = Conv3D(8, (3,3,3), activation='relu', padding='same')(conv3)
  pool3 = MaxPooling3D(pool_size=(2,2,2))(conv3)

  conv4 = Conv3D(64, (3,3,3), activation='relu', padding='same')(pool3)
  conv4 = Conv3D(64, (3,3,3), activation='relu', padding='same')(conv4)

  up5 = concatenate([UpSampling3D(size=(2,2,2))(conv4), conv3], axis=4)
  conv5 = Conv3D(8, (3,3,3), activation='relu', padding='same')(up5)
  conv5 = Conv3D(8, (3,3,3), activation='relu', padding='same')(conv5)

  up6 = concatenate([UpSampling3D(size=(2,2,2))(conv5), conv2], axis=4)
  conv6 = Conv3D(4, (3,3,3), activation='relu', padding='same')(up6)
  conv6 = Conv3D(4, (3,3,3), activation='relu', padding='same')(conv6)

  up7 = concatenate([UpSampling3D(size=(2,2,2))(conv6), conv1], axis=4)
  conv7 = Conv3D(2, (3,3,3), activation='relu', padding='same')(up7)
  conv7 = Conv3D(2, (3,3,3), activation='relu', padding='same')(conv7)

  conv8 = Conv3D(1, (1,1,1), activation='sigmoid')(conv7)

  model = Model(inputs=[inputs], outputs=[conv8])
  model.compile(optimizer = Adam(lr = learnrate), \
                loss = cross_entropy_balanced, metrics = ['accuracy'])

  return model

def getDefaultUnet2D(setup,isclassification,steps,nroutputs,
                    learnrate=keras_dict['learnrate'],
                    data_format='channels_first'):
  redirect_stdout()
  import keras
  restore_stdout()
  from keras.layers import (concatenate,Conv2D,Input,MaxPooling2D,UpSampling2D)
  from keras.models import Model
  from keras.optimizers import Adam

  if data_format == 'channels_first':
    stepout = (steps[1],steps[2],1)
  else:
    stepout = steps

  inputs = Input(stepout)

  conv1 = Conv2D(2, (3,3), activation='relu', padding='same')(inputs)
  conv1 = Conv2D(2, (3,3), activation='relu', padding='same')(conv1)
  pool1 = MaxPooling2D(pool_size=(2,2))(conv1)

  conv2 = Conv2D(4, (3,3), activation='relu', padding='same')(pool1)
  conv2 = Conv2D(4, (3,3), activation='relu', padding='same')(conv2)
  pool2 = MaxPooling2D(pool_size=(2,2))(conv2)

  conv3 = Conv2D(8, (3,3), activation='relu', padding='same')(pool2)
  conv3 = Conv2D(8, (3,3), activation='relu', padding='same')(conv3)
  pool3 = MaxPooling2D(pool_size=(2,2))(conv3)

  conv4 = Conv2D(64, (3,3), activation='relu', padding='same')(pool3)
  conv4 = Conv2D(64, (3,3), activation='relu', padding='same')(conv4)

  up5 = concatenate([UpSampling2D(size=(2,2))(conv4), conv3], axis=3)
  conv5 = Conv2D(8, (3,3), activation='relu', padding='same')(up5)
  conv5 = Conv2D(8, (3,3), activation='relu', padding='same')(conv5)

  up6 = concatenate([UpSampling2D(size=(2,2))(conv5), conv2], axis=3)
  conv6 = Conv2D(4, (3,3), activation='relu', padding='same')(up6)
  conv6 = Conv2D(4, (3,3), activation='relu', padding='same')(conv6)

  up7 = concatenate([UpSampling2D(size=(2,2))(conv6), conv1], axis=3)
  conv7 = Conv2D(2, (3,3), activation='relu', padding='same')(up7)
  conv7 = Conv2D(2, (3,3), activation='relu', padding='same')(conv7)

  conv8 = Conv2D(1, (1,1), activation='sigmoid')(conv7)

  model = Model(inputs=[inputs], outputs=[conv8])
  model.compile(optimizer = Adam(lr = learnrate), \
                loss = cross_entropy_balanced, metrics = ['accuracy'])

  return model

def train(model,training,params=keras_dict,trainfile=None,logdir=None):
  redirect_stdout()
  import keras
  restore_stdout()
  infos = training[dgbkeys.infodictstr]
  classification = infos[dgbkeys.classdictstr]
  if classification:
    monitor = 'acc'
  else:
    monitor = 'loss'
  early_stopping = EarlyStopping(monitor=monitor, patience=params['patience'])
  LR_sched = adaptive_schedule(params['learnrate'],params['epochdrop'])
  callbacks = [early_stopping,LR_sched]
  batchsize = params['batch']
  if logdir != None:
    tensor_board = TensorBoard(log_dir=logdir, histogram_freq=1, \
                               batch_size=batchsize,\
                         write_graph=True, write_grads=False, write_images=True)
    callbacks.append( tensor_board )
  nbchunks = len( infos[dgbkeys.trainseldicstr] )
  x_train = {}
  y_train = {}
  doshuffle = False
  decimate = nbchunks > 1
  if not decimate:
    if not dgbkeys.xtraindictstr in training:
      log_msg('No data to train the model')
      return model
    x_train = training[dgbkeys.xtraindictstr]
    y_train = training[dgbkeys.ytraindictstr]
    x_validate = training[dgbkeys.xvaliddictstr]
    y_validate = training[dgbkeys.yvaliddictstr]
  for ichunk in range(nbchunks):
    log_msg('Starting iteration',str(ichunk+1)+'/'+str(nbchunks))
    log_msg('Starting training data creation:')
    if decimate and trainfile != None:
      import dgbpy.mlapply as dgbmlapply
      trainbatch = dgbmlapply.getScaledTrainingDataByInfo( infos, flatten=False,
                                                 scale=True, ichunk=ichunk )
      if not dgbkeys.xtraindictstr in trainbatch:
        continue
      x_train = trainbatch[dgbkeys.xtraindictstr]
      y_train = trainbatch[dgbkeys.ytraindictstr]
      x_validate = trainbatch[dgbkeys.xvaliddictstr]
      y_validate = trainbatch[dgbkeys.yvaliddictstr]
    log_msg('Finished creating',len(x_train),'examples!')
    log_msg('Validation done on', len(x_validate), 'examples.' )
    while len(x_train.shape) < 5:
      x_train = np.expand_dims(x_train,axis=len(x_train.shape)-1)
    if classification:
      nrclasses = getNrClasses(model)
      y_train = keras.utils.to_categorical(y_train,nrclasses)
      y_validate = keras.utils.to_categorical(y_validate,nrclasses)
    redirect_stdout()
    hist = model.fit(x=x_train,y=y_train,callbacks=callbacks,\
                  shuffle=doshuffle, validation_data=(x_validate,y_validate),\
                  batch_size=batchsize, \
                  epochs=params['epoch'])
    #log_msg( hist.history )
    restore_stdout()

  keras.utils.print_summary( model, print_fn=log_msg )
  return model

def save( model, outfnm ):
  model.save( outfnm )

def load( modelfnm ):
  redirect_stdout()
  from keras.models import load_model
  ret = load_model( modelfnm, compile=False )
  restore_stdout()
  return ret

def apply( model, samples, isclassification, withpred, withprobs, withconfidence, doprobabilities, scaler=None, batch_size=keras_dict['batch'] ):
  redirect_stdout()
  import keras
  restore_stdout()
  ret = {}
  res = None
  if getDataFormat(model) == 'channels_last':
    samples = transform( samples )
    
  if withpred:
    if isclassification:
      res = model.predict_classes( samples, batch_size=batch_size )
    else:
      res = model.predict( samples, batch_size=batch_size )
      res = res.transpose()
      #TODO: make one output array for each column
    ret.update({dgbkeys.preddictstr: res})
 
  if isclassification and (doprobabilities or withconfidence):
    allprobs = model.predict( samples, batch_size=batch_size )
    if doprobabilities:
      res = np.copy(allprobs[:,withprobs],allprobs.dtype)
      ret.update({dgbkeys.probadictstr: res})
    if withconfidence:
      N = 2
      indices = np.argpartition(allprobs,-N,axis=1)[:,-N:]
      x = len(allprobs)
      sortedprobs = allprobs[np.repeat(np.arange(x),N),indices.ravel()].reshape(x,N)
      res = np.diff(sortedprobs,axis=1)
      ret.update({dgbkeys.confdictstr: res})

  return ret

def transform( samples ):
  nrsamples = samples.shape[0]
  nrattribs = samples.shape[1]
  cube_shape = samples.shape[2:]
  ret = np.empty( (nrsamples, cube_shape[0], cube_shape[1], cube_shape[2], nrattribs ), dtype = samples.dtype )
  for iattr in range(nrattribs):
    ret[:,:,:,:,iattr] = samples[:,iattr]
  return ret

def transformBack( samples ):
  nrsamples = samples.shape[0]
  cube_shape = samples.shape[1:-1]
  nrattribs = samples.shape[-1]
  ret = np.empty( (nrsamples, nrattribs, cube_shape[0], cube_shape[1], cube_shape[2] ), dtype = samples.dtype )
  for iattr in range(nrattribs):
    ret[:,iattr] = samples[:,:,:,:,iattr]
  return ret

def plot( model, outfnm, showshapes=True, withlaynames=False, vertical=True ):
  try:
    import pydot
  except ImportError:
    log_msg( 'Cannot plot the model without pydot module' )
    return
  rankdir = 'TB'
  if not vertical:
    rankdir = 'LR'
  from keras.utils import plot_model
  plot_model( model, to_file=outfnm, show_shapes=showshapes,
              show_layer_names=withlaynames, rankdir=rankdir )

def compute_capability_from_device_desc(device_desc):
  match = re.search(r"compute capability: (\d+)\.(\d+)", \
                      device_desc.physical_device_desc)
  if not match:
    return 0, 0
  return int(match.group(1)), int(match.group(2))

def getDevicesInfo( gpusonly=True ):
  from tensorflow.python.client import device_lib
  local_device_protos = device_lib.list_local_devices()
  if gpusonly:
    ret = [x for x in local_device_protos if x.device_type == 'GPU']
  else:
    ret = [x for x in local_device_protos]
  return ret

def is_gpu_ready():
  import tensorflow as tf
  devs = getDevicesInfo()
  if len(devs) < 1:
    return False
  cc = compute_capability_from_device_desc( devs[0] )
  return tf.test.is_gpu_available(True,cc)
