#
# (C) dGB Beheer B.V.; (LICENSE) http://opendtect.org/OpendTect_license.txt
# AUTHOR   : Arnaud Huck
# DATE     : December 2018
#
# Script for deep learning train
# is called by the DeepLearning plugin
#


from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                             QFileDialog,
                             QFrame, QFormLayout, QHBoxLayout, QLineEdit,
                             QPushButton, QSizePolicy,
                             QSpinBox, QVBoxLayout, QWidget)
from odpy.common import *

def getSpinBox(min,max,defval):
  ret = QSpinBox()
  ret.setRange(min,max)
  ret.setValue(defval)
  ret.setSizePolicy( QSizePolicy.Fixed, QSizePolicy.Preferred )
  return ret

def getFileInput(filenm):
  ret = QHBoxLayout()
  inpfilefld = QLineEdit(filenm)
  inpfilefld.setMinimumWidth(200)
  fileselbut = QPushButton('Select')
  ret.addWidget(inpfilefld)
  ret.addWidget(fileselbut)
  return (ret, inpfilefld, fileselbut)

def selectInput(parent,dlgtitle,dirnm,filters,lineoutfld):
  newfilenm = QFileDialog.getOpenFileName(parent,dlgtitle,dirnm,filters)
  lineoutfld.setText( newfilenm[0] )

def addSeparator(layout):
  linesep = QFrame()
  linesep.setFrameShape(QFrame.HLine)
  linesep.setFrameShadow(QFrame.Raised)
  layout.addWidget( linesep )

class WidgetGallery(QDialog):
  def __init__(self, args, parent=None):
    super(WidgetGallery, self).__init__(parent)
    self.args = args
    self.h5filenm = args['h5file'].name

    mainform = QFormLayout()
    mainform.setLabelAlignment( Qt.AlignRight )
    self.createInputGroupBox( mainform )
    self.createParametersGroupBox( mainform )
    self.createOutputGroupBox( mainform )
    self.createButtonsBox()

    mainlayout = QVBoxLayout()
    mainlayout.addLayout( mainform )
    addSeparator( mainlayout  )
    mainlayout.addLayout( self.buttonslayout )
    self.setLayout( mainlayout )

  def createInputGroupBox(self,layout):
    (self.inputfld, self.filenmfld, self.fileselbut) = getFileInput( self.h5filenm )
    layout.addRow( "&Train data", self.inputfld )
    layout.labelForField(self.inputfld).setBuddy(self.fileselbut)
    self.fileselbut.clicked.connect(lambda: selectInput(self,"Select training dataset",
                                                os.path.dirname( self.filenmfld.text() ),
                                                "HDF5 Files (*.hdf5 *.h5)",
                                                self.filenmfld) )

    if has_log_file():
      logfile = get_log_file()
      (self.logfld, self.lognmfld, self.logselbut) = getFileInput( logfile )
      layout.addRow( "&Log File", self.logfld )
      layout.labelForField(self.logfld).setBuddy(self.logselbut)
      self.logselbut.clicked.connect(lambda: selectInput(self,"Select Log File",
                                                os.path.dirname( logfile ),
                                                "Log Files (*.txt *.TXT *.log)",
                                                self.lognmfld) )

  def createParametersGroupBox(self,layout):
    self.dodecimate = QCheckBox( "&Decimate input" )
    self.dodecimate.setTristate( False )
    self.dodecimate.setChecked( False )
    self.decimatefld = getSpinBox(1,99,10)
    self.decimatefld.setSuffix("%")
    self.decimatefld.setDisabled( True )
    self.dodecimate.toggled.connect(self.decimatefld.setEnabled)
    self.iterfld = getSpinBox(1,100,15)
    self.iterfld.setDisabled( True )
    self.dodecimate.toggled.connect(self.iterfld.setEnabled)
    self.epochfld = getSpinBox(1,1000,15)
    self.batchfld = getSpinBox(1,1000,16)
    self.patiencefld = getSpinBox(1,1000,10)

    layout.addRow( self.dodecimate, self.decimatefld )
    layout.addRow( "Number of &Iterations", self.iterfld )
    layout.addRow( "Number of &Epochs", self.epochfld )
    layout.addRow( "Number of &Batch", self.batchfld )
    layout.addRow( "&Patience", self.patiencefld )

  def createOutputGroupBox(self,layout):
    self.modelfld = QLineEdit("<new model>")
    layout.addRow( "&Output model", self.modelfld )

  def createButtonsBox(self):
    buttons = QDialogButtonBox()
    self.runbutton =  buttons.addButton( QDialogButtonBox.Apply )
    self.runbutton.setText("Run")
    self.closebutton = buttons.addButton( QDialogButtonBox.Close )
    self.runbutton.clicked.connect(self.doApply)
    self.closebutton.clicked.connect(self.reject)

    self.buttonslayout = QVBoxLayout()
    self.buttonslayout.addWidget( buttons )

  def getParams(self):
    ret = {
      'decimation': None,
      'num_tot_iterations': 1,
      'epochs': self.epochfld.value(),
      'batch_size': self.batchfld.value(),
      'opt_patience': self.patiencefld.value()
    }
    if self.dodecimate.isChecked():
      ret['decimation'] = self.decimatefld.value()
      ret['num_tot_iterations'] = self.iterfld.value()
    return ret

  def doApply(self):
    params = self.getParams();
    success = doTrain( params, self.filenmfld.text(), self.modelfld.text(), self.args )

def setStyleSheet( app, args ):
  qtstylesheet = args['qtstylesheet']
  if qtstylesheet == None:
    return
  cssfile = qtstylesheet[0]
  qtcss = qtstylesheet[0].read()
  cssfile.close()
  app.setStyleSheet( qtcss )

def doTrain(params,trainfile,outnm,args):
  import dgbpy.mlio as dgbmlio
  training = dgbmlio.getTrainingData( trainfile, params['decimation'] )
  import dgbpy.dgbkeras as dgbkeras
  model = dgbkeras.getDefaultModel(training['info'])
  model = dgbkeras.train( model, training, params, trainfile=trainfile )
  outfnm = None
  try:
    outfnm = dgbmlio.getSaveLoc( args, outnm )
  except FileNotFoundError:
    raise
  dgbkeras.save( model, trainfile, outfnm )
  return os.path.isfile( outfnm )


if __name__ == '__main__':

    import sys
    import os
    import argparse
    import signal

    parser = argparse.ArgumentParser(prog='PROG',description='Select parameters for training a Keras model')
    parser.add_argument('-v','--version',action='version',version='%(prog)s 1.0')
    parser.add_argument('h5file',type=argparse.FileType('r'),help='HDF5 file containing the training data')
    datagrp = parser.add_argument_group('Data')
    datagrp.add_argument('--dataroot',dest='dtectdata',metavar='DIR',nargs=1,
                         help='Survey Data Root')
    datagrp.add_argument('--survey',dest='survey',nargs=1,
                         help='Survey name')
    odappl = parser.add_argument_group('OpendTect application')
    odappl.add_argument('--dtectexec',metavar='DIR',nargs=1,help='Path to OpendTect executables')
    odappl.add_argument('--qtstylesheet',metavar='qss',nargs=1,type=argparse.FileType('r'),
                        help='Qt StyleSheet template')
    loggrp = parser.add_argument_group('Logging')
    loggrp.add_argument('--log',dest='logfile',metavar='file',nargs='?',type=argparse.FileType('a'),
                        default='sys.stdout',help='Progress report output')
    loggrp.add_argument('--syslog',dest='sysout',metavar='stdout',nargs='?',type=argparse.FileType('a'),
                        default='sys.stdout',help='Standard output')
    args = vars(parser.parse_args())
    initLogging(args)

    app = QApplication(['Keras Model training'])
    gallery = WidgetGallery(args)
    gallery.show()
    setStyleSheet( app, args )

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.exit(app.exec_()) 
